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

# v2.24.11 Settings
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

            # v2.24.11 SIZE FIX - 80MB se bari hai to compress
            if file_size_mb > 80:
                await msg.edit(f"🗜️ **Compressing...** `{file_size_mb:.1f}MB` > Target ~70MB")
                cmd = [
                    'ffmpeg', '-threads', '1', '-i', file,
                    '-vf', f"scale=-2:720,{vf_filter}", # 1080p > 720p
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-maxrate', '2M', '-bufsize', '4M',
                    '-c:a', 'aac', '-b:a', '96k', # audio compress
                    output, '-y'
                ]
            else:
                await msg.edit("🎬 Watermark laga rahe...")
                cmd = [
                    'ffmpeg', '-threads', '1', '-i', file,
                    '-vf', vf_filter,
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24',
                    '-c:a', 'copy',
                    output, '-y'
                ]

            proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)
            _, stderr = await proc.communicate()

            if proc.returncode!= 0:
                error_text = stderr.decode()
                print(f"FFMPEG ERROR: {error_text}")
                first_line = error_text.split('\n')[0][:300]
                raise Exception(f"FFmpeg Error: {first_line}")

        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            await event.reply(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}`")
        else:
            if event.id in queue_messages:
                await client.delete_messages(user_id, queue_messages[event.id])

            final_size_mb = os.path.getsize(output) / (1024*1024)
            await client.send_file(
                event.chat_id, output,
                caption=f"✅ Done | Size: `{file_size_mb:.1f}MB` > `{final_size_mb:.1f}MB`",
                reply_to=event.id,
                force_document=True,
                progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
            )
            await msg.delete()
            if os.path.exists(output): os.remove(output)

        if DELETE_ORIGINAL: await event.delete()

    except Exception as e:
        if msg:
            err = str(e)[:4000]
            await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {err}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
        except: pass

@client.on(events.NewMessage(pattern=r'^/login'))
async def login_handler(event):
    parts = event.text.split(maxsplit=1)
    if len(parts) < 2: return await event.reply('🔑 Please enter password')
    if parts[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**')
    else: await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern=r'^/nowm'))
async def nowm_handler(event):
    global NO_WM_MODE
    if event.sender_id not in AUTHORIZED_USERS: return
    NO_WM_MODE = not NO_WM_MODE
    await event.reply(f"✅ **No WM Mode:** `{NO_WM_MODE}`")

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        return await event.reply('🔒 `/login password`')
    await queue.put((event, event.sender_id))

async def main():
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online v2.24.11 SIZE FIX")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())