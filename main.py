import os
import asyncio
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError # NEW
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
    if percent % 20 == 0 or percent == 100: # 10% se 20% kar diya - kam spam
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
        await asyncio.sleep(1) # NEW: Rate limit se bachne ke liye

        file = await event.download_media(
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id)
        )

        if event.id in cancel_flags:
            raise Exception("Cancelled")

        await msg.edit("🎬 Watermark laga rahe...")

        # FILENAME LOGIC
        if NAME_MODE == "original":
            if event.file and event.file.name:
                output = event.file.name
            else:
                output = f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            if event.file and event.file.name:
                output = f"{CUSTOM_PREFIX}{event.file.name}"
            else:
                output = f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        cmd = [
            'ffmpeg', '-i', file,
            '-vf', f"drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=h/25:x=(w-text_w)/2:y=(h-text_h)/2:fontcolor={CURRENT_COLOR}",
            '-c:a', 'copy', '-preset', 'ultrafast', output, '-y'
        ]

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
            event.chat_id,
            output,
            caption=f"✅ Done | {CURRENT_WATERMARK}",
            reply_to=event.id,
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
        )

        if DELETE_ORIGINAL:
            await event.delete()

        await msg.delete()

    except FloodWaitError as e: # NEW: Telegram limit handle
        wait_time = e.seconds
        if msg:
            await msg.edit(f"⏳ Telegram limit: {wait_time}s wait kar raha hu...")
        await asyncio.sleep(wait_time)
        if msg:
            await msg.edit("✅ Ab dobara video bhejo")

    except Exception as e:
        if msg:
            if "Cancelled" in str(e):
                await msg.edit("🚫 Cancelled")
            else:
                await msg.edit(f"❌ Failed: {str(e)[:100]}")
    finally:
        try:
            if file and os.path.exists(file):
                os.remove(file)
            if output and os.path.exists(output):
                os.remove(output)
        except:
            pass

@client.on(events.NewMessage(pattern='/login'))
async def login_handler(event):
    if len(event.text.split()) < 2:
        PENDING_STATES[event.sender_id] = "login"
        await event.reply('Please enter password')
        return

    if event.text.split()[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**\n\nAb tum bot use kar sakte ho.\n`/help` likho commands ke liye.')
    else:
        await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern='/(set|color|delete|setname)'))
async def command_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return

    cmd = event.text.split()[0][1:]

    if len(event.text.split()) > 1:
        value = event.text[len(cmd)+2:].strip()
        await set_value(event, cmd, value)
        return

    PENDING_STATES[event.sender_id] = cmd

    prompts = {
        "set": "Please enter watermark text",
        "color": "Please enter color. Example: `white@0.8` or `red@1.0`",
        "delete": "Please enter `on` or `off`",
        "setname": "Enter mode: `original`, `water_id`, ya `custom Prefix_`"
    }
    await event.reply(prompts.get(cmd))

@client.on(events.NewMessage(func=lambda e: e.sender_id in PENDING_STATES and not e.text.startswith('/')))
async def input_handler(event):
    if event.sender_id not in PENDING_STATES:
        return

    state = PENDING_STATES.pop(event.sender_id)
    value = event.text.strip()

    if state == "login":
        if value == BOT_PASSWORD:
            AUTHORIZED_USERS.add(event.sender_id)
            await event.reply('✅ **Login Success!**\n\n`/help` likho commands ke liye.')
        else:
            await event.reply('❌ Galat password. Dobara `/login` karo.')
        await event.delete()
        return

    await set_value(event, state, value)

async def set_value(event, cmd, value):
    global CURRENT_WATERMARK, CURRENT_COLOR, DELETE_ORIGINAL, NAME_MODE, CUSTOM_PREFIX

    if cmd == "set":
        CURRENT_WATERMARK = value
        await event.reply(f"✅ **Watermark Updated**\n`{value}`")

    elif cmd == "color":
        CURRENT_COLOR = value
        await event.reply(f"✅ **Color Updated**\n`{value}`")

    elif cmd == "delete":
        if value.lower() == 'on':
            DELETE_ORIGINAL = True
            await event.reply("✅ **Delete Original: ON**")
        elif value.lower() == 'off':
            DELETE_ORIGINAL = False
            await event.reply("✅ **Delete Original: OFF**")
        else:
            await event.reply("❌ Sirf `on` ya `off` likho")

    elif cmd == "setname":
        if value.lower() == "original":
            NAME_MODE = "original"
            await event.reply("✅ **Name Mode:** Original filename use hoga")
        elif value.lower() == "water_id":
            NAME_MODE = "water_id"
            await event.reply("✅ **Name Mode:** `water_12345.mp4` jaisa")
        elif value.lower().startswith("custom"):
            prefix = value[7:].strip() if len(value) > 6 else "wm_"
            CUSTOM_PREFIX = prefix
            NAME_MODE = "custom"
            await event.reply(f"✅ **Custom Prefix:** `{prefix}`\nExample: `{prefix}video.mp4`")
        else:
            await event.reply("❌ **Usage:** `original`, `water_id`, ya `custom Prefix_`")

@client.on(events.NewMessage(pattern='/dark'))
async def dark_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    CURRENT_COLOR = "white@0.8"
    await event.reply("✅ **Dark Mode ON**\nColor: `white@0.8`")

@client.on(events.NewMessage(pattern='/light'))
async def light_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    CURRENT_COLOR = "white@0.3"
    await event.reply("✅ **Light Mode ON**\nColor: `white@0.3`")

@client.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    if event.sender_id in AUTHORIZED_USERS:
        AUTHORIZED_USERS.remove(event.sender_id)
        await event.reply("✅ **Logged Out!**")
    else:
        await event.reply("❌ Tum login hi nahi ho")

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
        f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
        f"**Name Mode:** `{NAME_MODE}`\n"
        f"**Custom Prefix:** `{prefix_text}`\n"
        f"**Max Concurrent:** `{MAX_CONCURRENT}`\n"
        f"**Queue:** `{queue.qsize()}` | **Processing:** `{len(processing)}`"
    )

@client.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return

    if event.is_reply:
        reply_msg = await event.get_reply_message()
        cancel_flags[reply_msg.id] = True
        await event.reply("🚫 **Cancelling this video...**")
        return

    count = 0
    while not queue.empty():
        try:
            q_event = queue.get_nowait()
            cancel_flags[q_event.id] = True
            count += 1
            queue.task_done()
        except:
            break

    for pid in list(processing):
        cancel_flags[pid] = True
        count += 1

    if count > 0:
        await event.reply(f"🚫 **Cancelled {count} videos**")
    else:
        await event.reply("❌ **No videos in queue**")

@client.on(events.NewMessage(pattern='/help|/start'))
async def help_handler(event):
    await event.reply(
        "**🔥 Watermark Bot - Full Commands**\n\n"
        "**🔐 Auth:**\n"
        "`/login` - Bot unlock karo\n"
        "`/logout` - Bot lock karo\n\n"
        "**⚙️ Settings:**\n"
        "`/set` - Watermark text\n"
        "`/color` - Color + opacity\n"
        "`/dark` - Dark watermark\n"
        "`/light` - Light watermark\n"
        "`/delete` - Original delete on/off\n"
        "`/setname` - Filename mode\n"
        "`/current` - Settings dekho\n\n"
        "**📋 Queue:**\n"
        "`/cancel` - Sab cancel karo\n"
        "Reply + `/cancel` - 1 video cancel\n\n"
        "**📹 Video bhejo** - Watermark lag jayega"
    )

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 **Bot Locked**\n\nPassword daalo: `/login`')
        return

    await queue.put(event)
    pos = queue.qsize() + len(processing)
    # Queue message spam fix - sirf 2 se zyada pe bhej
    if pos > 2:
        await event.reply(f"⏳ **Queue #{pos-1}** - Waiting...")
        await asyncio.sleep(1) # Rate limit bachao

async def main():
    print("="*50)
    print("WATERMARK BOT - FIXED VERSION")
    print("="*50)
    print(f"Password: {BOT_PASSWORD}")
    print(f"Watermark: {CURRENT_WATERMARK}")
    print(f"Color: {CURRENT_COLOR}")
    print(f"Delete Original: {DELETE_ORIGINAL}")
    print(f"Name Mode: {NAME_MODE}")
    print(f"Max Concurrent: {MAX_CONCURRENT}")
    print("="*50)

    for _ in range(MAX_CONCURRENT):
        asyncio.create_task(worker())

    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online! Telegram me /login bhejo")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())