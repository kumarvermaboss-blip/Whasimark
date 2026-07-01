import asyncio
import os
from telethon import TelegramClient, events
import subprocess

# === CONFIG ===
API_ID = 37785994 # Apna daal
API_HASH = '8037023119:AAGsH3DtPiIDQbovREgXFCkjKvXE8-E0-BA'
BOT_TOKEN = 'your_bot_token'
BOT_PASSWORD = "Wasi123"

WATERMARK = '@WasiXD'
MAX_CONCURRENT = 2

client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# === GLOBALS ===
AUTHORIZED_USERS = set()
PENDING_STATES = {}

CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "white@0.8"
DELETE_ORIGINAL = False
NAME_MODE = "water_id" # water_id, original, custom
CUSTOM_PREFIX = "wm_"

queue = asyncio.Queue()
processing = set()
tasks = {}

# === LOGIN SYSTEM ===
@client.on(events.NewMessage(pattern='/login'))
async def login_handler(event):
    if len(event.text.split()) > 1:
        if event.text.split()[1] == BOT_PASSWORD:
            AUTHORIZED_USERS.add(event.sender_id)
            await event.reply('✅ **Login Success!**\n\n`/help` likho commands ke liye.')
        else:
            await event.reply('❌ Galat password.')
        return

    PENDING_STATES[event.sender_id] = "login"
    await event.reply('Please enter password')

# === MAIN COMMANDS - STEP BY STEP ===
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
        "setname": "Enter mode: `original`, `water_id`, ya `custom`"
    }
    await event.reply(prompts.get(cmd))

# === REPLY PAKADNE WALA HANDLER ===
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

    if state == "setname_prefix":
        global CUSTOM_PREFIX, NAME_MODE
        CUSTOM_PREFIX = value
        NAME_MODE = "custom"
        await event.reply(f"✅ **Custom Prefix Set:** `{value}`\nExample: `{value}video.mp4`")
        return

    await set_value(event, state, value)

# === VALUE SET KARNE KA FUNCTION ===
async def set_value(event, cmd, value):
    global CURRENT_WATERMARK, CURRENT_COLOR, DELETE_ORIGINAL, NAME_MODE

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
        elif value.lower() == "custom":
            PENDING_STATES[event.sender_id] = "setname_prefix"
            await event.reply("Please enter custom prefix. Example: `WasiXD_`")
        else:
            await event.reply("❌ Sirf `original`, `water_id` ya `custom` likho")

# === SIMPLE COMMANDS ===
@client.on(events.NewMessage(pattern='/(dark|light|logout|current|cancel|help|start)'))
async def simple_commands(event):
    global CURRENT_COLOR

    if event.text in ['/dark', '/light', '/current'] and event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return

    if event.text == '/dark':
        CURRENT_COLOR = "white@0.8"
        await event.reply("✅ **Dark Mode ON** `white@0.8`")

    elif event.text == '/light':
        CURRENT_COLOR = "white@0.3"
        await event.reply("✅ **Light Mode ON** `white@0.3`")

    elif event.text == '/logout':
        if event.sender_id in AUTHORIZED_USERS:
            AUTHORIZED_USERS.remove(event.sender_id)
            await event.reply("✅ **Logged Out!**")
        else:
            await event.reply("❌ Tum login hi nahi ho")

    elif event.text == '/current':
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

    elif event.text == '/cancel':
        if event.sender_id in tasks:
            tasks[event.sender_id].cancel()
            await event.reply("✅ **Cancelled**")
        else:
            await event.reply("❌ Koi active task nahi")

    elif event.text in ['/start', '/help']:
        await event.reply(
            "**🎬 Watermark Bot Help**\n\n"
            "**Login:**\n"
            "`/login` - Login karo\n"
            "`/logout` - Logout\n\n"
            "**Settings:**\n"
            "`/set` - Watermark text\n"
            "`/color` - Color + opacity: `white@0.8`\n"
            "`/dark` - White 80%\n"
            "`/light` - White 30%\n"
            "`/delete` - Original delete on/off\n"
            "`/setname` - Output filename mode\n"
            "`/current` - Current settings\n\n"
            "**Usage:**\n"
            "Video bhej do, watermark lag jayega\n"
            "`/cancel` - Processing cancel karo\n\n"
            "**Note:** Sab commands step-by-step hain. Ya ek saath bhi likh sakte ho: `/set @WasiXD`"
        )

# === VIDEO PROCESSING ===
async def progress_callback(current, total, msg, text, reply_id):
    percent = int(current / total * 100)
    try:
        await msg.edit(f"**{text}:** {percent}%", reply_to=reply_id)
    except:
        pass

@client.on(events.NewMessage(func=lambda e: e.video or e.document))
async def video_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return

    if not event.video and not (event.document and event.document.mime_type.startswith('video')):
        return

    if len(processing) >= MAX_CONCURRENT:
        await queue.put(event)
        pos = queue.qsize()
        await event.reply(f"⏳ **Queue Position:** {pos}\n`{MAX_CONCURRENT}` videos already processing.")
        return

    await process_video(event)

async def process_video(event):
    processing.add(event.id)
    msg = await event.reply("📥 **Downloading...**")

    try:
        file = await client.download_media(
            event.media,
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id)
        )

        # === FILENAME LOGIC ===
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
        else: # water_id default
            output = f"water_{event.id}.mp4"

        cmd = [
            'ffmpeg', '-i', file,
            '-vf', f"drawtext=text='{CURRENT_WATERMARK}':fontcolor={CURRENT_COLOR}:fontsize=24:x=(w-text_w)/2:y=h-text_h-20",
            '-c:a', 'copy',
            '-preset', 'fast',
            '-y', output
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        tasks[event.sender_id] = proc
        await proc.communicate()

        if proc.returncode!= 0:
            await msg.edit("❌ **FFmpeg Error**")
            return

        await msg.edit("📤 **Uploading...**")

        await client.send_file(
            event.chat_id,
            output,
            caption="✅ Done",
            reply_to=event.id,
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id)
        )

        if DELETE_ORIGINAL:
            await event.delete()

        await msg.delete()
        os.remove(file)
        os.remove(output)

    except asyncio.CancelledError:
        await msg.edit("❌ **Cancelled**")
        if 'file' in locals() and os.path.exists(file):
            os.remove(file)
        if 'output' in locals() and os.path.exists(output):
            os.remove(output)
    except Exception as e:
        await msg.edit(f"❌ **Error:** {str(e)}")
    finally:
        processing.discard(event.id)
        if event.sender_id in tasks:
            del tasks[event.sender_id]

        if not queue.empty():
            next_event = await queue.get()
            await process_video(next_event)

print("✅ Bot Started")
client.run_until_disconnected()