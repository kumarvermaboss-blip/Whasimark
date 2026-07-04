import os
import asyncio
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
import subprocess

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
WATERMARK = os.environ.get("WATERMARK", "@WasiXD")
FONT_FILE = os.environ.get("FONT_FILE", "DejaVuSans.ttf")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

client = TelegramClient('bot_session', API_ID, API_HASH)

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
AUTHORIZED_USERS = set()
PENDING_STATES = {}

# Default Settings
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "white@0.8"
DELETE_ORIGINAL = False
NAME_MODE = "water_id"
CUSTOM_PREFIX = "wm_"
WATERMARK_MODE = "bouncing" # bouncing ya static

async def worker():
    while True:
        event = await queue.get()
        async with semaphore:
            if event.id in cancel_flags:
                del cancel_flags[event.id]
                queue.task_done()
                continue
            processing.add(event.id)
            try:
                await process_video(event)
            except Exception as e:
                if event.id not in cancel_flags and "Cancelled" not in str(e):
                    try:
                        await event.reply(f"❌ Error: {str(e)[:100]}")
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

async def process_video(event):
    msg = None
    file = None
    output = None
    try:
        msg = await event.reply(f"⏳ Processing...")
        await asyncio.sleep(1)
        file = await event.download_media(
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id)
        )
        if event.id in cancel_flags:
            raise Exception("Cancelled")
        await msg.edit("🎬 Watermark laga rahe...")

        # FILENAME LOGIC
        if NAME_MODE == "original":
            output = event.file.name if event.file and event.file.name else f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            output = f"{CUSTOM_PREFIX}{event.file.name}" if event.file and event.file.name else f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        # WATERMARK MODE SELECT - FIXED BOUNCING
        if WATERMARK_MODE == "bouncing":
            # FIX: max/min lagaya taake text frame se bahar na jaye
            vf_filter = f"drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=h/22:x='max(0\\,min(w-text_w\\,abs(mod(120*t\\,w*2)-w)))':y='max(0\\,min(h-text_h\\,abs(mod(90*t\\,h*2)-h)))':fontcolor={CURRENT_COLOR}:shadowcolor=black@0.6:shadowx=2:shadowy=2:box=1:boxcolor=black@0.2:boxborderw=5"
        else:
            vf_filter = f"drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=h/25:x=(w-text_w)/2:y=(h-text_h)/2:fontcolor={CURRENT_COLOR}"

        cmd = ['ffmpeg', '-i', file, '-vf', vf_filter, '-c:a', 'copy', '-preset', 'ultrafast', output, '-y']
        proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE)

        while proc.returncode is None:
            if event.id in cancel_flags:
                proc.kill()
                raise Exception("Cancelled by user")
            await asyncio.sleep(0.5)
            try:
                await asyncio.wait_for(proc.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

        if proc.returncode!= 0:
            raise Exception("FFmpeg failed")

        await client.send_file(
            event.chat_id, output,
            caption=f"✅ Done | Mode: {WATERMARK_MODE} | {CURRENT_WATERMARK}",
            reply_to=event.id,
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
        )

        if DELETE_ORIGINAL:
            await event.delete()
        await msg.delete()

    except FloodWaitError as e:
        if msg:
            await msg.edit(f"⏳ Telegram limit: {e.seconds}s wait...")
        await asyncio.sleep(e.seconds)
        if msg:
            await msg.edit("✅ Ab dobara video bhejo")
    except Exception as e:
        if msg:
            await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {str(e)[:100]}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
            if output and os.path.exists(output): os.remove(output)
        except: pass

@client.on(events.NewMessage(pattern='/login'))
async def login_handler(event):
    if len(event.text.split()) < 2:
        PENDING_STATES[event.sender_id] = "login"
        await event.reply('Please enter password')
        return
    if event.text.split()[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**\n\n`/help` likho commands ke liye.')
    else:
        await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern='/wmmode'))
async def wmmode_handler(event):
    global WATERMARK_MODE
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    if WATERMARK_MODE == "bouncing":
        WATERMARK_MODE = "static"
        await event.reply("✅ **Watermark Mode: Static Center**")
    else:
        WATERMARK_MODE = "bouncing"
        await event.reply("✅ **Watermark Mode: Bouncing**")

@client.on(events.NewMessage(pattern='/(set|color|delete|setname)'))
async def command_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    cmd = event.text.split()[0][1:]
    if len(event.text.split()) > 1:
        await set_value(event, cmd, event.text[len(cmd)+2:].strip())
        return
    PENDING_STATES[event.sender_id] = cmd
    prompts = {"set": "Please enter watermark text", "color": "Please enter color. Example: `white@0.8`", "delete": "Please enter `on` or `off`", "setname": "Enter mode: `original`, `water_id`, ya `custom Prefix_`"}
    await event.reply(prompts.get(cmd))

@client.on(events.NewMessage(func=lambda e: e.sender_id in PENDING_STATES and not e.text.startswith('/')))
async def input_handler(event):
    if event.sender_id not in PENDING_STATES: return
    state = PENDING_STATES.pop(event.sender_id)
    await set_value(event, state, event.text.strip())
    if state == "login": await event.delete()

async def set_value(event, cmd, value):
    global CURRENT_WATERMARK, CURRENT_COLOR, DELETE_ORIGINAL, NAME_MODE, CUSTOM_PREFIX
    if cmd == "set": CURRENT_WATERMARK = value; await event.reply(f"✅ **Watermark Updated**\n`{value}`")
    elif cmd == "color": CURRENT_COLOR = value; await event.reply(f"✅ **Color Updated**\n`{value}`")
    elif cmd == "delete": DELETE_ORIGINAL = True if value.lower() == 'on' else False; await event.reply(f"✅ **Delete Original: {value.upper()}**")
    elif cmd == "setname":
        if value.lower() == "original": NAME_MODE = "original"; await event.reply("✅ **Name Mode:** Original")
        elif value.lower() == "water_id": NAME_MODE = "water_id"; await event.reply("✅ **Name Mode:** `water_id`")
        elif value.lower().startswith("custom"): CUSTOM_PREFIX = value[7:].strip() if len(value) > 6 else "wm_"; NAME_MODE = "custom"; await event.reply(f"✅ **Custom Prefix:** `{CUSTOM_PREFIX}`")
        else: await event.reply("❌ Usage: `original`, `water_id`, ya `custom Prefix_`")

@client.on(events.NewMessage(pattern='/dark'))
async def dark_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    CURRENT_COLOR = "white@0.8"; await event.reply("✅ **Dark Mode ON**")

@client.on(events.NewMessage(pattern='/light'))
async def light_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    CURRENT_COLOR = "white@0.3"; await event.reply("✅ **Light Mode ON**")

@client.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    if event.sender_id in AUTHORIZED_USERS: AUTHORIZED_USERS.remove(event.sender_id); await event.reply("✅ **Logged Out!**")
    else: await event.reply("❌ Tum login hi nahi ho")

@client.on(events.NewMessage(pattern='/current'))
async def current_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    prefix_text = CUSTOM_PREFIX if NAME_MODE == "custom" else "N/A"
    await event.reply(
        f"**📊 Current Settings:**\n\n"
        f"**Watermark:** `{CURRENT_WATERMARK}`\n"
        f"**Color:** `{CURRENT_COLOR}`\n"
        f"**WM Mode:** `{WATERMARK_MODE}`\n"
        f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
        f"**Name Mode:** `{NAME_MODE}`\n"
        f"**Custom Prefix:** `{prefix_text}`\n"
        f"**Max Concurrent:** `{MAX_CONCURRENT}`\n"
        f"**Queue:** `{queue.qsize()}` | **Processing:** `{len(processing)}`"
    )

@client.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if event.is_reply:
        cancel_flags[(await event.get_reply_message()).id] = True
        return await event.reply("🚫 **Cancelling this video...**")
    count = 0
    while not queue.empty():
        try: cancel_flags[queue.get_nowait().id] = True; count += 1; queue.task_done()
        except: break
    for pid in list(processing): cancel_flags[pid] = True; count += 1
    await event.reply(f"🚫 **Cancelled {count} videos**" if count > 0 else "❌ **No videos in queue**")

@client.on(events.NewMessage(pattern='/help|/start'))
async def help_handler(event):
    await event.reply(
        "**🔥 Watermark Bot - Bouncing Edition**\n\n"
        "**🔐 Auth:** `/login` `/logout`\n"
        "**⚙️ Settings:** `/set` `/color` `/wmmode` `/dark` `/light` `/delete` `/setname` `/current`\n"
        "**📋 Queue:** `/cancel` or Reply + `/cancel`\n\n"
        "**📹 Video bhejo** - Watermark lag jayega"
    )

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        return await event.reply('🔒 **Bot Locked**\n\nPassword daalo: `/login`')
    await queue.put(event)
    pos = queue.qsize() + len(processing)
    if pos > 2: await event.reply(f"⏳ **Queue #{pos-1}** - Waiting...")

async def main():
    print(f"BOT STARTED | WM: {CURRENT_WATERMARK} | Mode: {WATERMARK_MODE} | Color: {CURRENT_COLOR}")
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())