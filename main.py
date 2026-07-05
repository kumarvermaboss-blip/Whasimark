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
FONT_FILE = os.environ.get("FONT_FILE", "DejaVuSans.ttf")
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

# Settings
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "white@1"
DELETE_ORIGINAL = False
NAME_MODE = "water_id"
CUSTOM_PREFIX = "wm_"
WATERMARK_MODE = "bouncing"
ZIP_MODE = False
NO_WM_MODE = False
ZIP_QUEUE = []
WM_PERCENT = 0.05 # Screen ka 5%. 0.03 = 3%, 0.08 = 8%

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
                if event.id not in cancel_flags and "Cancelled" not in str(e):
                    try:
                        await event.reply(f"❌ Error: {str(e)[:500]}")
                    except:
                        pass
            finally:
                processing.discard(event.id)
                if event.id in cancel_flags:
                    del cancel_flags[event.id]
                queue.task_done()

async def progress_callback(current, total, msg, action, event_id):
    if event_id in cancel_flags:
        raise Exception("Cancelled by user")
    percent = int(current * 100 / total)
    if percent % 25 == 0 or percent == 100:
        try:
            await msg.edit(f"{action} {percent}%")
        except:
            pass

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

        file = await event.download_media(
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id)
        )
        if event.id in cancel_flags:
            raise Exception("Cancelled")

        # FILENAME
        if NAME_MODE == "original":
            output = event.file.name if event.file and event.file.name else f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            output = f"{CUSTOM_PREFIX}{event.file.name}" if event.file and event.file.name else f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        # SAFE WATERMARK - FFmpeg 7 ke liye
        safe_watermark = CURRENT_WATERMARK.replace("'", "\\'").replace(":", "\\:").replace("%", "%%").replace("[", "\\[").replace("]", "\\]")

        # NO WM MODE
        if NO_WM_MODE:
            await msg.edit("📦 **No Watermark Mode** - Sirf copy kar raha")
            shutil.copy(file, output)
        else:
            await msg.edit("🎬 Watermark laga rahe...")

            # STEP 1: Video ki width/height
            probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                         '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', file]
            probe = await asyncio.create_subprocess_exec(*probe_cmd, stdout=asyncio.subprocess.PIPE)
            stdout, _ = await probe.communicate()
            w, h = map(int, stdout.decode().strip().split('x'))

            # STEP 2: % BASED SIZE
            dynamic_size = int(w * WM_PERCENT)
            final_size = max(20, min(150, dynamic_size))

            # STEP 3: Bounce Area
            text_w = final_size * 0.5 * len(safe_watermark)
            text_h = final_size
            margin = int(w * 0.02)

            max_x = max(margin, w - text_w - margin)
            max_y = max(margin, h - text_h - margin)

            if WATERMARK_MODE == "bouncing":
                speed_x = w / 10
                speed_y = h / 12
                x_formula = f"clamp({margin}\\,mod({speed_x}*t\\,{max_x})\\,{max_x})"
                y_formula = f"clamp({margin}\\,mod({speed_y}*t\\,{max_y})\\,{max_y})"
            else:
                x_formula = f"clamp({margin}\\,{margin}\\,{max_x})"
                y_formula = f"clamp({margin}\\,{margin}\\,{max_y})"

            vf_filter = f"drawtext=text='{safe_watermark}':fontsize={final_size}:fontcolor={CURRENT_COLOR}:x='{x_formula}':y='{y_formula}'"

            cmd = ['ffmpeg', '-i', file, '-vf', vf_filter, '-c:a', 'copy', output, '-y']
            proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()
            
            if proc.returncode!= 0:
                error_text = stderr.decode()
                print(f"FFMPEG FULL ERROR: {error_text}")
                raise Exception(f"FFmpeg failed: {error_text}")

        # ZIP MODE
        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            wm_status = "No WM" if NO_WM_MODE else f"WM: {WATERMARK_MODE} {int(WM_PERCENT*100)}%"
            msg2 = await event.reply(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}` videos\nMode: `{wm_status}`\n`/zipnow` = Foran zip")
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
                caption=f"✅ Done | {'No WM' if NO_WM_MODE else f'WM: {WATERMARK_MODE} Size: {final_size}px'}",
                reply_to=event.id,
                force_document=True,
                progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
            )
            await msg.delete()
            if os.path.exists(output): os.remove(output)

        if DELETE_ORIGINAL:
            await event.delete()

    except Exception as e:
        if msg:
            await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {str(e)}")
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
            backup_caption = f"""📦 **New Zip Backup**
**User:** {username} `ID: {user_id}`
**Total Videos:** {total}
**Mode:** {mode}
**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}"""
            await client.send_file(BACKUP_CHANNEL, zip_name, caption=backup_caption)
        except Exception as e: print(f"❌ Backup Error: {e}")
    for video in ZIP_QUEUE:
        if os.path.exists(video): os.remove(video)
    if os.path.exists(zip_name): os.remove(zip_name)
    ZIP_QUEUE = []

# ===== COMMANDS =====
@client.on(events.NewMessage(pattern=r'^/login'))
async def login_handler(event):
    parts = event.text.split(maxsplit=1)
    if len(parts) < 2:
        PENDING_STATES[event.sender_id] = "login"
        await event.reply('🔑 Please enter password')
        return
    if parts[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**\n\n`/help` likho commands ke liye.')
    else: await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern=r'^/logout'))
async def logout_handler(event):
    if event.sender_id in AUTHORIZED_USERS:
        AUTHORIZED_USERS.remove(event.sender_id)
        await event.reply('✅ **Logout Success**')
    else: await event.reply('❌ Pehle login hi nahi kiya')

@client.on(events.NewMessage(pattern=r'^/nowm'))
async def nowm_toggle(event):
    global NO_WM_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    NO_WM_MODE = not NO_WM_MODE
    status = "ON" if NO_WM_MODE else "OFF"
    await event.reply(f"✅ **No Watermark Mode: {status}**")

@client.on(events.NewMessage(pattern=r'^/zip$'))
async def zip_toggle(event):
    global ZIP_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    ZIP_MODE = not ZIP_MODE
    status = "ON" if ZIP_MODE else "OFF"
    msg = "✅ **Zip Mode: ON**\nAb videos queue me jayengi" if ZIP_MODE else "✅ **Zip Mode: OFF**\nAb videos direct send hongi"
    await event.reply(msg)

@client.on(events.NewMessage(pattern=r'^/zipnow$'))
async def zip_now(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if len(ZIP_QUEUE) == 0: return await event.reply("❌ **Zip Queue khali hai**")
    user = await client.get_entity(event.sender_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"
    await event.reply(f"⏳ **{len(ZIP_QUEUE)} videos ki zip bana raha hun...**")
    await create_and_send_zip(event.chat_id, username, event.sender_id)

@client.on(events.NewMessage(pattern=r'^/wmmode'))
async def wmmode_handler(event):
    global WATERMARK_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    WATERMARK_MODE = "static" if WATERMARK_MODE == "bouncing" else "bouncing"
    await event.reply(f"✅ **Watermark Mode: {WATERMARK_MODE.title()}**")

@client.on(events.NewMessage(pattern=r'^/wmpercent'))
async def wmpercent_handler(event):
    global WM_PERCENT
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        try:
            percent = float(parts[1])
            if 0.01 <= percent <= 0.20:
                WM_PERCENT = percent
                await event.reply(f"✅ **WM Size:** `{int(WM_PERCENT*100)}%` of screen width")
            else: await event.reply("❌ 0.01 se 0.20 ke beech me rakho. Ex: `/wmpercent 0.05`")
        except: await event.reply("❌ Usage: `/wmpercent 0.05`")
    else:
        PENDING_STATES[event.sender_id] = "wmpercent"
        await event.reply("Enter % in decimal: `0.05` = 5%")

@client.on(events.NewMessage(pattern=r'^/color'))
async def color_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        CURRENT_COLOR = parts[1].strip()
        await event.reply(f"✅ **Watermark Color:** `{CURRENT_COLOR}`")
    else:
        PENDING_STATES[event.sender_id] = "color"
        await event.reply("Enter color with opacity: `white@1` ya `red@0.9`")

@client.on(events.NewMessage(pattern=r'^/delete'))
async def delete_handler(event):
    global DELETE_ORIGINAL
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        DELETE_ORIGINAL = True if parts[1].lower() == 'on' else False
        await event.reply(f"✅ **Delete Original: {DELETE_ORIGINAL}**")
    else:
        PENDING_STATES[event.sender_id] = "delete"
        await event.reply("Enter `on` or `off`")

@client.on(events.NewMessage(pattern=r'^/set'))
async def set_handler(event):
    global CURRENT_WATERMARK
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        CURRENT_WATERMARK = parts[1].strip()
        await event.reply(f"✅ **Watermark Updated**\n`{CURRENT_WATERMARK}`")
    else:
        PENDING_STATES[event.sender_id] = "set"
        await event.reply("Please enter watermark text")

@client.on(events.NewMessage(pattern=r'^/setname'))
async def setname_handler(event):
    global NAME_MODE, CUSTOM_PREFIX
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    parts = event.text.split(maxsplit=1)
    if len(parts) > 1:
        val = parts[1].strip()
        if val == "original": NAME_MODE = "original"; await event.reply("✅ **Name Mode:** Original")
        elif val == "water_id": NAME_MODE = "water_id"; await event.reply("✅ **Name Mode:** water_id")
        elif val.startswith("custom"): CUSTOM_PREFIX = val[7:].strip() if len(val) > 6 else "wm_"; NAME_MODE = "custom"; await event.reply(f"✅ **Custom Prefix:** `{CUSTOM_PREFIX}`")
        else: await event.reply("❌ Usage: `original`, `water_id`, ya `custom Prefix_`")
    else:
        PENDING_STATES[event.sender_id] = "setname"
        await event.reply("Enter: `original`, `water_id`, ya `custom Prefix_`")

@client.on(events.NewMessage(func=lambda e: e.sender_id in PENDING_STATES and not e.text.startswith('/')))
async def input_handler(event):
    global CURRENT_WATERMARK, DELETE_ORIGINAL, NAME_MODE, CUSTOM_PREFIX, CURRENT_COLOR, WM_PERCENT
    if event.sender_id not in PENDING_STATES: return
    state = PENDING_STATES.pop(event.sender_id)
    txt = event.text.strip()
    if state == "set": CURRENT_WATERMARK = txt; await event.reply(f"✅ **Watermark Updated**\n`{txt}`")
    elif state == "delete": DELETE_ORIGINAL = True if txt.lower() == 'on' else False; await event.reply(f"✅ **Delete Original: {DELETE_ORIGINAL}**")
    elif state == "color": CURRENT_COLOR = txt; await event.reply(f"✅ **Watermark Color:** `{CURRENT_COLOR}`")
    elif state == "wmpercent":
        try:
            percent = float(txt)
            if 0.01 <= percent <= 0.20: WM_PERCENT = percent; await event.reply(f"✅ **WM Size:** `{int(WM_PERCENT*100)}%`")
            else: await event.reply("❌ 0.01 se 0.20 ke beech me rakho")
        except: await event.reply("❌ Number bhejo")
    elif state == "setname":
        if txt == "original": NAME_MODE = "original"; await event.reply("✅ **Name Mode:** Original")
        elif txt == "water_id": NAME_MODE = "water_id"; await event.reply("✅ **Name Mode:** water_id")
        elif txt.startswith("custom"): CUSTOM_PREFIX = txt[7:].strip() if len(txt) > 6 else "wm_"; NAME_MODE = "custom"; await event.reply(f"✅ **Custom Prefix:** `{CUSTOM_PREFIX}`")
    elif state == "login":
        if txt == BOT_PASSWORD: AUTHORIZED_USERS.add(event.sender_id); await event.reply('✅ **Login Success!**')
        else: await event.reply('❌ Galat password.')
    await event.delete()

@client.on(events.NewMessage(pattern=r'^/current'))
async def current_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    zip_status = "ON" if ZIP_MODE else "OFF"
    nowm_status = "ON" if NO_WM_MODE else "OFF"
    prefix_text = CUSTOM_PREFIX if NAME_MODE == "custom" else "N/A"
    await event.reply(
        f"**📊 Current Settings v2.24.2:**\n\n"
        f"**Watermark:** `{CURRENT_WATERMARK}`\n"
        f"**WM Mode:** `{WATERMARK_MODE}`\n"
        f"**WM Size:** `{int(WM_PERCENT*100)}%` of screen width\n"
        f"**Color:** `{CURRENT_COLOR}`\n"
        f"**No WM Mode:** `{nowm_status}`\n"
        f"**Zip Mode:** `{zip_status}`\n"
        f"**Zip Queue:** `{len(ZIP_QUEUE)}` videos\n"
        f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
        f"**Name Mode:** `{NAME_MODE}`\n"
        f"**Custom Prefix:** `{prefix_text}`\n"
        f"**Backup Channel:** `{BACKUP_CHANNEL}`"
    )

@client.on(events.NewMessage(pattern=r'^/cancel'))
async def cancel_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if event.is_reply:
        cancel_flags[(await event.get_reply_message()).id] = True
        return await event.reply("🚫 **Cancelling this video...**")
    count = 0
    while not queue.empty():
        try: cancel_flags[queue.get_nowait()[0].id] = True; count += 1; queue.task_done()
        except: break
    for pid in list(processing): cancel_flags[pid] = True; count += 1
    await event.reply(f"🚫 **Cancelled {count} videos**" if count > 0 else "❌ **No videos in queue**")

@client.on(events.NewMessage(pattern=r'^/help|^/start'))
async def help_handler(event):
    await event.reply(
        "**🔥 Text Watermark + Zip Bot v2.24.2**\n\n"
        "**🔐 Auth:** \n`/login password` `/logout`\n\n"
        "**⚙️ Settings:** \n`/set text` `/wmpercent 0.05` `/color white@1`\n`/wmmode` `/nowm`\n`/delete on/off` `/setname` `/current`\n\n"
        "**📦 Zip:** \n`/zip` = ON/OFF Toggle\n`/zipnow` = Foran Zip Banao\n"
        "**📋 Queue:** \n`/cancel`\n\n"
        "**New:** % Based Size + FFmpeg 7 Fix"
    )

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        return await event.reply('🔒 **Bot Locked**\n\n`/login password`')
    await queue.put((event, event.sender_id))

async def main():
    print("BOT STARTED v2.24.2 - % Based WM + FFmpeg 7 Fix")
    print(f"Backup Channel ID: {BACKUP_CHANNEL}")
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())