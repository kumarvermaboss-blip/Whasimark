import os
import asyncio
from telethon import TelegramClient, events
import subprocess

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
WATERMARK = os.environ.get("WATERMARK", "@WasiXD")
FONT_FILE = os.environ.get("FONT_FILE", "DejaVuSans.ttf")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))

# Bot mode me start karo
client = TelegramClient('bot_session', API_ID, API_HASH)

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
AUTHORIZED_USERS = set()

# Default Settings - Chat se change ho sakte hain
CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "white@0.8"
DELETE_ORIGINAL = False

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
                    await event.reply(f"❌ Error: {str(e)[:100]}")
            finally:
                processing.discard(event.id)
                if event.id in cancel_flags:
                    del cancel_flags[event.id]
                queue.task_done()

async def progress_callback(current, total, msg, action, event_id):
    if event_id in cancel_flags:
        raise Exception("Cancelled by user")
    percent = int(current * 100 / total)
    if percent % 10 == 0 or percent == 100:
        try:
            await msg.edit(f"{action} {percent}%")
        except:
            pass

async def process_video(event):
    msg = await event.reply(f"⏳ Queue me #{len(processing)+1} | Starting...")
    file = None
    output = None

    try:
        file = await event.download_media(
            progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id)
        )

        if event.id in cancel_flags:
            raise Exception("Cancelled")

        await msg.edit("🎬 Processing...")
        output = f"wm_{event.id}.mp4"

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

    except Exception as e:
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
        await event.reply('Password bhi bhejo: `/login Wasi123`')
        return
    if event.text.split()[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ **Login Success!**\n\nAb tum bot use kar sakte ho.\n`/help` likho commands ke liye.')
    else:
        await event.reply('❌ Galat password.')

@client.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    if event.sender_id in AUTHORIZED_USERS:
        AUTHORIZED_USERS.remove(event.sender_id)
        await event.reply("✅ **Logged Out!**\nBot ab lock hai.")
    else:
        await event.reply("❌ Tum login hi nahi ho")

@client.on(events.NewMessage(pattern='/set'))
async def set_wm_handler(event):
    global CURRENT_WATERMARK
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    new_wm = event.text[5:].strip()
    if new_wm:
        CURRENT_WATERMARK = new_wm
        await event.reply(f"✅ **Watermark Updated**\n`{new_wm}`")
    else:
        await event.reply("❌ **Usage:** `/set @YourText`")

@client.on(events.NewMessage(pattern='/color'))
async def set_color_handler(event):
    global CURRENT_COLOR
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    new_color = event.text[7:].strip()
    if new_color:
        CURRENT_COLOR = new_color
        await event.reply(f"✅ **Color Updated**\n`{new_color}`\n\n**Examples:**\n`red@1.0` - Dark solid\n`white@0.3` - Light transparent")
    else:
        await event.reply("❌ **Usage:** `/color white@0.5` ya `/color red`")

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

@client.on(events.NewMessage(pattern='/delete'))
async def delete_toggle_handler(event):
    global DELETE_ORIGINAL
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    mode = event.text[8:].strip().lower()
    if mode == 'on':
        DELETE_ORIGINAL = True
        await event.reply("✅ **Delete Original: ON**\nAb original videos delete ho jayengi")
    elif mode == 'off':
        DELETE_ORIGINAL = False
        await event.reply("✅ **Delete Original: OFF**\nOriginal videos save rahengi")
    else:
        await event.reply("❌ **Usage:** `/delete on` ya `/delete off`")

@client.on(events.NewMessage(pattern='/current'))
async def current_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return
    await event.reply(
        f"**📊 Current Settings:**\n\n"
        f"**Watermark:** `{CURRENT_WATERMARK}`\n"
        f"**Color:** `{CURRENT_COLOR}`\n"
        f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
        f"**Max Concurrent:** `{MAX_CONCURRENT}`\n"
        f"**Queue:** `{queue.qsize()}` | **Processing:** `{len(processing)}`"
    )

@client.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 Pehle /login karo')
        return

    # Specific cancel
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        cancel_flags[reply_msg.id] = True
        await event.reply("🚫 **Cancelling this video...**")
        return

    # Cancel all
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
        "`/login password` - Bot unlock karo\n"
        "`/logout` - Bot lock karo\n\n"
        "**⚙️ Settings:**\n"
        "`/set @Text` - Watermark text\n"
        "`/color red@0.5` - Color + opacity\n"
        "`/dark` - Dark watermark\n"
        "`/light` - Light watermark\n"
        "`/delete on/off` - Original delete\n"
        "`/current` - Settings dekho\n\n"
        "**📋 Queue:**\n"
        "`/cancel` - Sab cancel karo\n"
        "Reply + `/cancel` - 1 video cancel\n\n"
        "**📹 Video bhejo** - Watermark lag jayega"
    )

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('🔒 **Bot Locked**\n\nPassword daalo: `/login your_password`')
        return

    await queue.put(event)
    pos = queue.qsize() + len(processing)
    if pos > 1:
        await event.reply(f"⏳ **Queue #{pos-1}** - Waiting...")

async def main():
    print("="*50)
    print("WATERMARK BOT - RAILWAY VERSION")
    print("="*50)
    print(f"Password: {BOT_PASSWORD}")
    print(f"Watermark: {CURRENT_WATERMARK}")
    print(f"Color: {CURRENT_COLOR}")
    print(f"Delete Original: {DELETE_ORIGINAL}")
    print(f"Max Concurrent: {MAX_CONCURRENT}")
    print("="*50)

    for _ in range(MAX_CONCURRENT):
        asyncio.create_task(worker())

    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online! Telegram me /login password bhejo")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())