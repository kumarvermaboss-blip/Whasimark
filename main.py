import os
import asyncio
from telethon import TelegramClient, events
import zipfile
import shutil
from datetime import datetime

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
BACKUP_CHANNEL = os.environ.get("BACKUP_CHANNEL")
if BACKUP_CHANNEL: BACKUP_CHANNEL = int(BACKUP_CHANNEL)

WATERMARK = os.environ.get("WATERMARK", "@bvsrv1")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

client = TelegramClient('bot_session', API_ID, API_HASH)

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
AUTHORIZED_USERS = set()
PENDING_STATES = {}
queue_messages = {}
zip_queue_messages = {}

# v2.24.9 Settings
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "red@1" # DEFAULT RED. White: /color white@1
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
                if event.id not in cancel_flags and "Cancelled" not in str(e):
                    try: await event.reply(f"❌ Error: {str(e)[:500]}")
                    except: pass
            finally:
                processing.discard(event.id)
                if event.id in cancel_flags: del cancel_flags[event.id]
                queue.task_done()

async def progress_callback(current, total, msg, action, event_id):
    if event_id in cancel_flags: raise Exception("Cancelled by user")
    percent = int(current * 100 / total)
    if percent % 25 == 0 or percent == 100:
        try:
            text = f"{action} {percent}%"
            if len(text) > 4000: text = text[:4000]
            await msg.edit(text)
        except: pass

async def process_video(event, user_id):
    global ZIP_QUEUE
    msg = None
    file = None
    output = None
    user = await client.get_entity(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"

    try:
        q_pos = queue.qsize() + len(processing)
        msg = await client.send_message(user_id, f"⏳ **Queue #{q_pos}**\nMode: {'No WM' if NO_WM_MODE else WATERMARK_MODE}")
        queue_messages[event.id] = msg.id

        file = await event.download_media(progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id))
        if event.id in cancel_flags: raise Exception("Cancelled")

        if NAME_MODE == "original":
            output = event.file.name if event.file and event.file.name else f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            output = f"{CUSTOM_PREFIX}{event.file.name}" if event.file and event.file.name else f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        safe_watermark = CURRENT_WATERMARK.replace("'", "\\'").replace(":", "\\:").replace("%", "%%").replace("[", "\\[").replace("]", "\\]")

        if NO_WM_MODE:
            await msg.edit("📦 **No Watermark Mode**")
            shutil.copy(file, output)
        else:
            await msg.edit("🎬 Watermark laga rahe...")

            probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', file]
            probe = await asyncio.create_subprocess_exec(*probe_cmd, stdout=asyncio.subprocess.PIPE)
            stdout, _ = await probe.communicate()
            w, h = map(int, stdout.decode().strip().split('x'))

            dynamic_size = int(w * WM_PERCENT)
            final_size = max(20, min(150, dynamic_size))

            text_w = final_size * 0.5 * len(safe_watermark)
            text_h = final_size
            margin = int(w * 0.02)
            max_x = max(margin, w - text_w - margin)
            max_y = max(margin, h - text_h - margin)

            if WATERMARK_MODE == "bouncing":
                speed_x = w / 10
                speed_y = h / 12
                x_formula = f"min(max({margin}\\,mod({speed_x}*t\\,{max_x}))\\,{max_x})"
                y_formula = f"min(max({margin}\\,mod({speed_y}*t\\,{max_y}))\\,{max_y})"
            else:
                x_formula = f"min(max({margin}\\,{margin})\\,{max_x})"
                y_formula = f"min(max({margin}\\,{margin})\\,{max_y})"

            # YAHAN FONT FIX LAGA DIYA HAI
            vf_filter = f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='{safe_watermark}':fontsize={final_size}:fontcolor={CURRENT_COLOR}:x='{x_formula}':y='{y_formula}'"
            cmd = ['ffmpeg', '-i', file, '-vf', vf_filter, '-c:a', 'copy', output, '-y']
            proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()

            if proc.returncode!= 0:
                error_text = stderr.decode()
                print(f"FFMPEG FULL ERROR: {error_text}")
                first_line = error_text.split('\n')[0][:200]
                raise Exception(f"FFmpeg Error: {first_line}")

        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            wm_status = "No WM" if NO_WM_MODE else f"WM: {WATERMARK_MODE} {int(WM_PERCENT*100)}%"
            msg2 = await event.reply(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}` videos\nMode: `{wm_status}`")
            if user_id not in zip_queue_messages: zip_queue_messages[user_id] = []
            zip_queue_messages[user_id].append(msg2.id)
            if event.id in queue_messages:
                await client.delete_messages(user_id, queue_messages[event.id])
                del queue_messages[event.id]
            if len(ZIP_QUEUE) >= 10:
                await create_and_send_zip(event.chat_id, username, user_id)
        else:
            if event.id in queue_messages:
                await client.delete_messages(user_id, queue_messages[event.id])
                del queue_messages[event.id]
            await client.send_file(
                event.chat_id, output,
                caption=f"✅ Done | {'No WM' if NO_WM_MODE else f'WM: {WATERMARK_MODE} Size: {final_size}px Color: {CURRENT_COLOR}'}",
                reply_to=event.id,
                force_document=True,
                progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
            )
            await msg.delete()
            if os.path.exists(output): os.remove(output)

        if DELETE_ORIGINAL: await event.delete()

    except Exception as e:
        if msg:
            error_text = str(e)
            if len(error_text) > 4000: error_text = error_text[:4000] + "..."
            await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {error_text}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
        except: pass

async def create_and_send_zip(chat_id, username, user_id):
    global ZIP_QUEUE
    if len(ZIP_QUEUE) == 0: return
    zip_name = f"Watermarked_{datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip"
    msg = await client.send_message(chat_id, f"📦 **Zip bana raha hun... {len(ZIP_QUEUE)} videos**")
    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for video in ZIP_QUEUE:
            if os.path.exists(video): zipf.write(video, os.path.basename(video))
    total = len(ZIP_QUEUE)
    mode = 'No WM' if NO_WM_MODE else f"{WATERMARK_MODE} {int(WM_PERCENT*100)}%"
    if user_id in zip_queue_messages and zip_queue_messages[user_id]:
        try: await client.delete_messages(chat_id, zip_queue_messages[user_id])
        except: pass
        del zip_queue_messages[user_id]
    await client.send_file(chat_id, zip_name, caption=f"📦 **Zip Ready**\nTotal: `{total}` videos\nMode: `{mode}`", force_document=True)
    await msg.delete()
    if BACKUP_CHANNEL:
        try:
            backup_caption = f"📦 **New Zip Backup**\n**User:** {username}\n**Total:** {total}\n**Mode:** {mode}"
            await client.send_file(BACKUP_CHANNEL, zip_name, caption=backup_caption)
        except Exception as e: print(f"❌ Backup Error: {e}")
    for video in ZIP_QUEUE:
        if os.path.exists(video): os.remove(video)
    if os.path.exists(zip_name): os.remove(zip_name)
    ZIP_QUEUE = []

@client.on(events.NewMessage(pattern=r'^/login'))
async def login_handler(event):
    parts = event.text.split(maxsplit=1)
    if len(parts) < 2:
        PENDING_STATES[event.sender_id] = "login"
        await event.reply('🔑 Please enter password')
        return
    if parts[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**\n\n`/help` for commands')
    else: await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern=r'^/color'))
async def color_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        CURRENT_COLOR = parts[1].strip()
        await event.reply(f"✅ **Watermark Color:** `{CURRENT_COLOR}`")
    else:
        await event.reply("**Color Examples:**\n`red@1` = Red\n`white@1` = White")

@client.on(events.NewMessage(pattern=r'^/help|^/start'))
async def help_handler(event):
    await event.reply(
        "**🔥 Text Watermark Bot v2.24.9 Final**\n\n"
        "**🔐 Auth:** `/login` `/logout`\n"
        "**⚙️ Settings:** `/set` `/color` `/wmpercent` `/wmmode` `/nowm`\n"
        "**📦 Zip:** `/zip` `/zipnow`\n"
        "**📋 Queue:** `/cancel` `/current`\n\n"
        "**Default Color:** `red@1`"
    )

@client.on(events.NewMessage(func=lambda e: e.sender_id in PENDING_STATES and not e.text.startswith('/')))
async def input_handler(event):
    global CURRENT_WATERMARK, DELETE_ORIGINAL, NAME_MODE, CUSTOM_PREFIX, CURRENT_COLOR, WM_PERCENT
    if event.sender_id not in PENDING_STATES: return
    state = PENDING_STATES.pop(event.sender_id)
    txt = event.text.strip()
    if state == "set": CURRENT_WATERMARK = txt; await event.reply(f"✅ **Watermark Updated**\n`{txt}`")
    elif state == "color": CURRENT_COLOR = txt; await event.reply(f"✅ **Watermark Color:** `{CURRENT_COLOR}`")
    elif state == "login":
        if txt == BOT_PASSWORD: AUTHORIZED_USERS.add(event.sender_id); await event.reply('✅ **Login Success!**')
        else: await event.reply('❌ Galat password.')
    await event.delete()

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        return await event.reply('🔒 **Bot Locked**\n\n`/login password`')
    await queue.put((event, event.sender_id))

async def main():
    print("BOT STARTED v2.24.9 - Final Font Fix")
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())