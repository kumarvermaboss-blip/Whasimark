import os
import asyncio
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
import subprocess
import zipfile
import shutil
from datetime import datetime

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
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

# Settings
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "red@0.9"
DELETE_ORIGINAL = False
NAME_MODE = "water_id"
CUSTOM_PREFIX = "wm_"
WATERMARK_MODE = "bouncing"
ZIP_MODE = False
NO_WM_MODE = False
ZIP_QUEUE = []

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
    global ZIP_QUEUE
    msg = None
    file = None
    output = None
    try:
        msg = await event.reply(f"⏳ Processing...")
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

        # NO WM MODE CHECK
        if NO_WM_MODE:
            await msg.edit("📦 **No Watermark Mode** - Sirf copy kar raha")
            shutil.copy(file, output)
        else:
            await msg.edit("🎬 Watermark laga rahe...")
            if WATERMARK_MODE == "bouncing":
                vf_filter = f"drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=45:fontcolor={CURRENT_COLOR}:x='max(0\\,min(W-tw\\,abs(mod(120*t\\,W*2)-W)))':y='max(0\\,min(H-th\\,abs(mod(90*t\\,H*2)-H)))'"
            else:
                vf_filter = f"drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=45:fontcolor={CURRENT_COLOR}:x=20:y=20"

            cmd = ['ffmpeg', '-i', file, '-vf', vf_filter, '-c:a', 'copy', output, '-y']
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

        # ZIP MODE
        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            wm_status = "No WM" if NO_WM_MODE else f"WM: {WATERMARK_MODE}"
            await msg.edit(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}` videos\nMode: `{wm_status}`\n`/zipnow` = Foran zip")
            if len(ZIP_QUEUE) >= 10:
                await create_and_send_zip(event.chat_id)
        else:
            await client.send_file(
                event.chat_id, output,
                caption=f"✅ Done | {'No Watermark' if NO_WM_MODE else f'WM: {WATERMARK_MODE}'}",
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
            await msg.edit("🚫 Cancelled" if "Cancelled" in str(e) else f"❌ Failed: {str(e)[:100]}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
        except: pass

async def create_and_send_zip(chat_id):
    global ZIP_QUEUE
    if len(ZIP_QUEUE) == 0: return

    zip_name = f"Watermarked_{datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip"
    msg = await client.send_message(chat_id, f"📦 **Zip bana raha hun... {len(ZIP_QUEUE)} videos**")

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for video in ZIP_QUEUE:
            if os.path.exists(video):
                zipf.write(video, os.path.basename(video))

    await client.send_file(
        chat_id, zip_name,
        caption=f"📦 **Zip Ready**\nTotal: `{len(ZIP_QUEUE)}` videos\nMode: `{'No WM' if NO_WM_MODE else WATERMARK_MODE}`",
        force_document=True
    )
    await msg.delete()

    for video in ZIP_QUEUE:
        if os.path.exists(video): os.remove(video)
    if os.path.exists(zip_name): os.remove(zip_name)
    ZIP_QUEUE = []

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

@client.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    if event.sender_id in AUTHORIZED_USERS:
        AUTHORIZED_USERS.remove(event.sender_id)
        await event.reply('✅ **Logout Success**')
    else:
        await event.reply('❌ Pehle login hi nahi kiya')

@client.on(events.NewMessage(pattern='/nowm'))
async def nowm_toggle(event):
    global NO_WM_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    NO_WM_MODE = not NO_WM_MODE
    status = "ON" if NO_WM_MODE else "OFF"
    await event.reply(f"✅ **No Watermark Mode: {status}**\n\nON = Sirf zip banegi, WM nahi lagega")

@client.on(events.NewMessage(pattern='/zip'))
async def zip_toggle(event):
    global ZIP_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    ZIP_MODE = not ZIP_MODE
    status = "ON" if ZIP_MODE else "OFF"
    await event.reply(f"✅ **Zip Mode: {status}**")

@client.on(events.NewMessage(pattern='/zipnow'))
async def zip_now(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if len(ZIP_QUEUE) == 0: return await event.reply("❌ **Zip Queue khali hai**")
    await create_and_send_zip(event.chat_id)

@client.on(events.NewMessage(pattern='/wmmode'))
async def wmmode_handler(event):
    global WATERMARK_MODE
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    WATERMARK_MODE = "static" if WATERMARK_MODE == "bouncing" else "bouncing"
    await event.reply(f"✅ **Watermark Mode: {WATERMARK_MODE.title()}**")

@client.on(events.NewMessage(pattern='/delete'))
async def delete_handler(event):
    global DELETE_ORIGINAL
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if len(event.text.split()) > 1:
        DELETE_ORIGINAL = True if event.text.split()[1].lower() == 'on' else False
        await event.reply(f"✅ **Delete Original: {DELETE_ORIGINAL}**")
    else:
        PENDING_STATES[event.sender_id] = "delete"
        await event.reply("Enter `on` or `off`")

@client.on(events.NewMessage(pattern='/set'))
async def set_handler(event):
    global CURRENT_WATERMARK
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if len(event.text.split()) > 1:
        CURRENT_WATERMARK = event.text[4:].strip()
        await event.reply(f"✅ **Watermark Updated**\n`{CURRENT_WATERMARK}`")
    else:
        PENDING_STATES[event.sender_id] = "set"
        await event.reply("Please enter watermark text")

@client.on(events.NewMessage(pattern='/setname'))
async def setname_handler(event):
    global NAME_MODE, CUSTOM_PREFIX
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    if len(event.text.split()) > 1:
        val = event.text[8:].strip()
        if val == "original": NAME_MODE = "original"; await event.reply("✅ **Name Mode:** Original")
        elif val == "water_id": NAME_MODE = "water_id"; await event.reply("✅ **Name Mode:** water_id")
        elif val.startswith("custom"): CUSTOM_PREFIX = val[7:].strip() if len(val) > 6 else "wm_"; NAME_MODE = "custom"; await event.reply(f"✅ **Custom Prefix:** `{CUSTOM_PREFIX}`")
        else: await event.reply("❌ Usage: `original`, `water_id`, ya `custom Prefix_`")
    else:
        PENDING_STATES[event.sender_id] = "setname"
        await event.reply("Enter: `original`, `water_id`, ya `custom Prefix_`")

@client.on(events.NewMessage(func=lambda e: e.sender_id in PENDING_STATES and not e.text.startswith('/')))
async def input_handler(event):
    global CURRENT_WATERMARK, DELETE_ORIGINAL, NAME_MODE, CUSTOM_PREFIX
    if event.sender_id not in PENDING_STATES: return
    state = PENDING_STATES.pop(event.sender_id)
    txt = event.text.strip()
    if state == "set": CURRENT_WATERMARK = txt; await event.reply(f"✅ **Watermark Updated**\n`{txt}`")
    elif state == "delete": DELETE_ORIGINAL = True if txt.lower() == 'on' else False; await event.reply(f"✅ **Delete Original: {DELETE_ORIGINAL}**")
    elif state == "setname":
        if txt == "original": NAME_MODE = "original"; await event.reply("✅ **Name Mode:** Original")
        elif txt == "water_id": NAME_MODE = "water_id"; await event.reply("✅ **Name Mode:** water_id")
        elif txt.startswith("custom"): CUSTOM_PREFIX = txt[7:].strip() if len(txt) > 6 else "wm_"; NAME_MODE = "custom"; await event.reply(f"✅ **Custom Prefix:** `{CUSTOM_PREFIX}`")
    elif state == "login":
        if txt == BOT_PASSWORD: AUTHORIZED_USERS.add(event.sender_id); await event.reply('✅ **Login Success!**')
        else: await event.reply('❌ Galat password.')
    await event.delete()

@client.on(events.NewMessage(pattern='/current'))
async def current_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 Pehle /login karo')
    zip_status = "ON" if ZIP_MODE else "OFF"
    nowm_status = "ON" if NO_WM_MODE else "OFF"
    prefix_text = CUSTOM_PREFIX if NAME_MODE == "custom" else "N/A"
    await event.reply(
        f"**📊 Current Settings:**\n\n"
        f"**Watermark:** `{CURRENT_WATERMARK}`\n"
        f"**WM Mode:** `{WATERMARK_MODE}`\n"
        f"**No WM Mode:** `{nowm_status}`\n"
        f"**Zip Mode:** `{zip_status}`\n"
        f"**Zip Queue:** `{len(ZIP_QUEUE)}` videos\n"
        f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
        f"**Name Mode:** `{NAME_MODE}`\n"
        f"**Custom Prefix:** `{prefix_text}`"
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
        "**🔥 Text Watermark + Zip Bot v2.1**\n\n"
        "**🔐 Auth:** \n`/login password` `/logout`\n\n"
        "**⚙️ Settings:** \n`/set text` `/wmmode` `/nowm`\n`/delete on/off` `/setname` `/current`\n\n"
        "**📦 Zip:** \n`/zip` ON/OFF `/zipnow`\n\n"
        "**📋 Queue:** \n`/cancel`\n\n"
        "**Pro Tip:**\n`/nowm` ON + `/zip` ON = Sirf zip, koi WM nahi"
    )

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        return await event.reply('🔒 **Bot Locked**\n\n`/login password`')
    await queue.put(event)
    pos = queue.qsize() + len(processing)
    if pos > 1: await event.reply(f"⏳ **Queue #{pos-1}**")

async def main():
    print("BOT STARTED v2.1")
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online!")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())