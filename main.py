import os
import asyncio
from telethon import TelegramClient, events, Button
import zipfile
import shutil

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
BACKUP_CHANNEL = os.environ.get("BACKUP_CHANNEL")
if BACKUP_CHANNEL: BACKUP_CHANNEL = int(BACKUP_CHANNEL)

WATERMARK = os.environ.get("WATERMARK", "@bvsrv1")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
MAX_SIZE_MB = 180 # v2.25.0 NEW LIMIT

client = TelegramClient('bot_session', API_ID, API_HASH)

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
AUTHORIZED_USERS = set()
PENDING_STATES = {}
queue_messages = {}
zip_queue_messages = {}

# v2.25.0 Settings
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "red@1"
DELETE_ORIGINAL = False
NAME_MODE = "water_id"
CUSTOM_PREFIX = "wm_"
WATERMARK_MODE = "bouncing"
ZIP_MODE = False
NO_WM_MODE = False
ZIP_QUEUE = []
WM_PERCENT = 0.05

async def worker():
    while True:
        event, user_id = await queue.get()
        async with semaphore:
            if event.id in cancel_flags:
                del cancel_flags[event.id]
                queue.task_done()
                continue
            processing.add(event.id)
            try:
                await process_video(event, user_id)
            except Exception as e:
                print(f"WORKER ERROR: {e}")
            finally:
                processing.discard(event.id)
                if event.id in cancel_flags: del cancel_flags[event.id]
                queue.task_done()

async def progress_callback(current, total, msg, action, event_id):
    if event_id in cancel_flags: raise Exception("Cancelled by user")
    percent = int(current * 100 / total)
    if percent % 20 == 0 or percent == 100:
        try: await msg.edit(f"{action} {percent}%")
        except: pass

async def process_video(event, user_id):
    global ZIP_QUEUE
    msg = None
    file = None
    output = None
    try:
        q_pos = queue.qsize() + len(processing)
        msg = await client.send_message(user_id, f"⏳ **Queue #{q_pos}**")
        queue_messages[event.id] = msg.id

        file = await event.download_media(progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id))
        if event.id in cancel_flags: raise Exception("Cancelled")

        if NAME_MODE == "original":
            output = event.file.name if event.file and event.file.name else f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            output = f"{CUSTOM_PREFIX}{event.file.name}" if event.file and event.file.name else f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        safe_watermark = CURRENT_WATERMARK.replace("'", "\\'").replace(":", "\\:").replace("%", "%%")
        file_size_mb = os.path.getsize(file) / (1024*1024)

        if NO_WM_MODE:
            await msg.edit("📦 **No Watermark Mode**")
            shutil.copy(file, output)
        else:
            probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', file]
            probe = await asyncio.create_subprocess_exec(*probe_cmd, stdout=asyncio.subprocess.PIPE)
            stdout, _ = await probe.communicate()
            w, h = map(int, stdout.decode().strip().split('x'))

            dynamic_size = int(w * WM_PERCENT)
            final_size = max(20, min(150, dynamic_size))

            text_w = final_size * 0.5 * len(safe_watermark)
            margin = int(w * 0.02)
            max_x = max(margin, w - text_w - margin)
            max_y = max(margin, h - final_size - margin)

            if WATERMARK_MODE == "bouncing":
                speed_x = w / 10
                speed_y = h / 12
                x_formula = f"min(max({margin}\\,mod({speed_x}*t\\,{max_x}))\\,{max_x})"
                y_formula = f"min(max({margin}\\,mod({speed_y}*t\\,{max_y}))\\,{max_y})"
            else:
                x_formula = f"{margin}"
                y_formula = f"{margin}"

            vf_filter = f"drawtext=fontfile=./DejaVuSans.ttf:text='{safe_watermark}':fontsize={final_size}:fontcolor={CURRENT_COLOR}:x='{x_formula}':y='{y_formula}'"

            if file_size_mb > 80:
                await msg.edit(f"🗜️ **Compressing...** `{file_size_mb:.1f}MB` > ~70MB")
                cmd = ['ffmpeg', '-threads', '1', '-i', file, '-vf', f"scale=-2:720,{vf_filter}", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-maxrate', '2M', '-bufsize', '4M', '-c:a', 'aac', '-b:a', '96k', output, '-y']
            else:
                await msg.edit("🎬 Watermark laga rahe...")
                cmd = ['ffmpeg', '-threads', '1', '-i', file, '-vf', vf_filter, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24', '-c:a', 'copy', output, '-y']

            proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()
            if proc.returncode!= 0: raise Exception(f"FFmpeg Error: {stderr.decode().split(chr(10))[0]}")

        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            await event.reply(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}`")
        else:
            if event.id in queue_messages: await client.delete_messages(user_id, queue_messages[event.id])
            final_size_mb = os.path.getsize(output) / (1024*1024)
            await client.send_file(event.chat_id, output, caption=f"✅ Done | Size: `{file_size_mb:.1f}MB` > `{final_size_mb:.1f}MB`", reply_to=event.id, force_document=True, progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id))
            await msg.delete()
            if os.path.exists(output): os.remove(output)
        if DELETE_ORIGINAL: await event.delete()
    except Exception as e:
        if msg: await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {str(e)[:4000]}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
        except: pass

# ===== WIZARD COMMANDS v2.25.0 =====
@client.on(events.NewMessage(pattern=r'^/start'))
async def start_handler(event):
    buttons = [
        [Button.inline('🔑 Bot Login', b'login'), Button.inline('🔒 Logout', b'logout')],
        [Button.inline('📊 Current Settings', b'current'), Button.inline('📖 Help', b'help')],
        [Button.inline('✏️ Set WM Text', b'set'), Button.inline('🎨 Set Color', b'color')],
        [Button.inline('📐 WM Size %', b'wmpercent'), Button.inline('🔄 WM Mode', b'wmmode')],
        [Button.inline('🚫 No WM', b'nowm'), Button.inline('🗑️ Delete Orig', b'delete')],
        [Button.inline('📝 File Name', b'setname'), Button.inline('📦 Zip Mode', b'zip')],
        [Button.inline('⬇️ Create Zip', b'zipnow'), Button.inline('❌ Cancel Queue', b'cancel')]
    ]
    await event.reply('**WMark Bot v2.25.0 Wizard**\nNeeche se setting select karo:', buttons=buttons)

@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode('utf-8')
    user_id = event.sender_id
    if data == 'login': await event.respond('🔑 Password bhejo: `/login password`')
    elif data == 'logout': AUTHORIZED_USERS.discard(user_id); await event.respond('✅ Logged Out')
    elif data == 'current': await event.respond(f"**Settings:**\nWM: `{CURRENT_WATERMARK}`\nColor: `{CURRENT_COLOR}`\nMode: `{WATERMARK_MODE}`\nSize%: `{WM_PERCENT}`\nZip: `{ZIP_MODE}`\nNoWM: `{NO_WM_MODE}`\nDelete: `{DELETE_ORIGINAL}`\nName: `{NAME_MODE}`")
    elif data == 'help': await event.respond('**Commands:**\n`/login pass` `/logout` `/set text` `/color red@1` `/wmpercent 0.05` `/wmmode` `/nowm` `/delete` `/setname original/custom/water_id` `/zip` `/zipnow` `/cancel`')
    elif data == 'set': PENDING_STATES[user_id] = 'set'; await event.respond('✏️ Naya watermark text bhejo')
    elif data == 'color': PENDING_STATES[user_id] = 'color'; await event.respond('🎨 Color bhejo: `red@1` `white@1` `yellow@1`')
    elif data == 'wmpercent': PENDING_STATES[user_id] = 'wmpercent'; await event.respond('📐 Size % bhejo: `0.03` to `0.08`')
    elif data == 'wmmode': global WATERMARK_MODE; WATERMARK_MODE = 'static' if WATERMARK_MODE=='bouncing' else 'bouncing'; await event.respond(f'✅ WM Mode: `{WATERMARK_MODE}`')
    elif data == 'nowm': global NO_WM_MODE; NO_WM_MODE = not NO_WM_MODE; await event.respond(f'✅ No WM: `{NO_WM_MODE}`')
    elif data == 'delete': global DELETE_ORIGINAL; DELETE_ORIGINAL = not DELETE_ORIGINAL; await event.respond(f'✅ Delete Original: `{DELETE_ORIGINAL}`')
    elif data == 'setname': PENDING_STATES[user_id] = 'setname'; await event.respond('📝 Mode bhejo: `original` `custom` `water_id`')
    elif data == 'zip': global ZIP_MODE; ZIP_MODE = not ZIP_MODE; await event.respond(f'✅ Zip Mode: `{ZIP_MODE}`')
    elif data == 'zipnow': await zip_handler(event)
    elif data == 'cancel': await cancel_handler(event)
    await event.answer()

@client.on(events.NewMessage)
async def pending_handler(event):
    user_id = event.sender_id
    if user_id in PENDING_STATES:
        state = PENDING_STATES.pop(user_id)
        text = event.text
        global CURRENT_WATERMARK, WM_PERCENT, NAME_MODE, CUSTOM_PREFIX
        if state == 'set': CURRENT_WATERMARK = text; await event.reply(f'✅ WM Text: `{text}`')
        elif state == 'color': global CURRENT_COLOR; CURRENT_COLOR = text; await event.reply(f'✅ Color: `{text}`')
        elif state == 'wmpercent': WM_PERCENT = float(text); await event.reply(f'✅ WM Size%: `{text}`')
        elif state == 'setname': NAME_MODE = text; CUSTOM_PREFIX = "wm_" if text=="custom" else ""; await event.reply(f'✅ Name Mode: `{text}`')

@client.on(events.NewMessage(pattern=r'^/login (.+)'))
async def login_handler(event):
    if event.text.split(maxsplit=1)[1] == BOT_PASSWORD: AUTHORIZED_USERS.add(event.sender_id); await event.reply('✅ **Login Success!**')
    else: await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern=r'^/logout'))
async def logout_handler(event): AUTHORIZED_USERS.discard(event.sender_id); await event.reply('✅ Logged Out')

@client.on(events.NewMessage(pattern=r'^/cancel'))
async def cancel_handler(event):
    cancel_flags[event.id] = True
    await event.reply("🚫 Queue Cancelled")

@client.on(events.NewMessage(pattern=r'^/zipnow'))
async def zip_handler(event):
    if not ZIP_QUEUE: return await event.reply("📦 Zip queue khali hai")
    zip_name = f"zip_{event.id}.zip"
    with zipfile.ZipFile(zip_name, 'w') as zipf:
        for f in ZIP_QUEUE: zipf.write(f, os.path.basename(f))
    await client.send_file(event.chat_id, zip_name)
    for f in ZIP_QUEUE: os.remove(f)
    ZIP_QUEUE.clear()
    os.remove(zip_name)
    await event.reply("✅ Zip bheja gaya")

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 `/login password`')

    # v2.25.0 SIZE CHECK - 180MB LIMIT
    if event.file and event.file.size > MAX_SIZE_MB * 1024 * 1024:
        return await event.reply(f"🚫 **Video too large**\nSize: `{event.file.size / (1024*1024):.1f}MB`\nLimit: `{MAX_SIZE_MB}MB`\n\nYe video skip kar di. Baki videos process hoti rahengi.")

    await queue.put((event, event.sender_id))

async def main():
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online v2.25.0 WIZARD + 180MB LIMIT")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())