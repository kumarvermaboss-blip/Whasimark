import asyncio
import os
import datetime
import zipfile
from telethon import TelegramClient, events

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

client = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
MAX_ZIP_VIDEOS = int(os.environ.get("MAX_ZIP_VIDEOS", "10"))
BACKUP_CHANNEL = os.environ.get("BACKUP_CHANNEL", None)

semaphore = asyncio.Semaphore(MAX_CONCURRENT)
queue = asyncio.Queue()
queue_messages = {}
zip_queue_messages = {}
zip_queue = {}
user_settings = {} # sab user ka data yahan

def get_user(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = {
            "logged_in": False,
            "wm_text": "No WM",
            "wm_mode": "static", # bouncing/static
            "zip_mode": False,
            "delete": False,
            "filename": "default"
        }
    return user_settings[user_id]

# ===== 1. /help =====
@client.on(events.NewMessage(pattern="/help"))
async def help_cmd(event):
    text = """**WMark Bot Commands**
/login - Login to bot
/logout - Logout from bot
/set - Set watermark text. Ex: /set @yourname
/wmmode - Toggle bouncing/static
/nowm - Toggle no watermark mode
/zip - Toggle zip mode
/zipnow - Send zip immediately
/delete - Delete original on/off
/setname - Set filename mode
/current - Show current settings
/cancel - Cancel all videos
/help - Show help message"""
    await event.reply(text)

# ===== 2. /login =====
@client.on(events.NewMessage(pattern="/login"))
async def login_cmd(event):
    user = get_user(event.sender_id)
    user["logged_in"] = True
    await event.reply("✅ Login Successful")

# ===== 3. /logout =====
@client.on(events.NewMessage(pattern="/logout"))
async def logout_cmd(event):
    user = get_user(event.sender_id)
    user["logged_in"] = False
    await event.reply("✅ Logout Successful")

# ===== 4. /set =====
@client.on(events.NewMessage(pattern="/set"))
async def set_cmd(event):
    user = get_user(event.sender_id)
    try:
        wm_text = event.text.split(" ", 1)[1]
        user["wm_text"] = wm_text
        await event.reply(f"✅ Watermark set to: `{wm_text}`")
    except:
        await event.reply("Use: `/set your watermark text`")

# ===== 5. /wmmode =====
@client.on(events.NewMessage(pattern="/wmmode"))
async def wmmode_cmd(event):
    user = get_user(event.sender_id)
    user["wm_mode"] = "bouncing" if user["wm_mode"] == "static" else "static"
    await event.reply(f"✅ WM Mode: {user['wm_mode']}")

# ===== 6. /nowm =====
@client.on(events.NewMessage(pattern="/nowm"))
async def nowm_cmd(event):
    user = get_user(event.sender_id)
    user["wm_text"] = "No WM" if user["wm_text"]!= "No WM" else "Watermark"
    await event.reply(f"✅ Mode: {user['wm_text']}")

# ===== 7. /zip =====
@client.on(events.NewMessage(pattern="/zip"))
async def zip_toggle(event):
    user = get_user(event.sender_id)
    user["zip_mode"] = not user["zip_mode"]
    status = "ON" if user["zip_mode"] else "OFF"
    await event.reply(f"✅ Zip Mode: {status}\nAb videos /zip me add hongi")

# ===== 8. /zipnow =====
@client.on(events.NewMessage(pattern="/zipnow"))
async def make_zip(event):
    user_id = event.sender_id
    user = await client.get_entity(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"
    settings = get_user(user_id)

    if user_id not in zip_queue or not zip_queue[user_id]:
        await client.send_message(user_id, "Zip queue is empty")
        return

    zip_name = f"Watermarked_{datetime.datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip"
    with zipfile.ZipFile(zip_name, 'w') as zipf:
        for file in zip_queue[user_id]:
            zipf.write(file)
            os.remove(file)

    total = len(zip_queue[user_id])
    mode = settings["wm_text"]

    if user_id in zip_queue_messages:
        await client.delete_messages(user_id, zip_queue_messages[user_id])
        del zip_queue_messages[user_id]

    await client.send_file(user_id, zip_name, caption=f"📦 Zip Ready\nTotal: {total} videos\nMode: {mode}")

    # SIRF ZIP KA BACKUP
    if BACKUP_CHANNEL:
        caption = f"""📦 New Zip Backup
**User:** {username} `ID: {user_id}`
**Total Videos:** {total}
**Mode:** {mode}
**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        await client.send_file(BACKUP_CHANNEL, zip_name, caption=caption)

    del zip_queue[user_id]
    os.remove(zip_name)

# ===== 9. /delete =====
@client.on(events.NewMessage(pattern="/delete"))
async def delete_toggle(event):
    user = get_user(event.sender_id)
    user["delete"] = not user["delete"]
    status = "ON" if user["delete"] else "OFF"
    await event.reply(f"✅ Delete Original: {status}")

# ===== 10. /setname =====
@client.on(events.NewMessage(pattern="/setname"))
async def setname_cmd(event):
    user = get_user(event.sender_id)
    try:
        name = event.text.split(" ", 1)[1]
        user["filename"] = name
        await event.reply(f"✅ Filename set to: `{name}`")
    except:
        await event.reply("Use: `/setname myvideo`")

# ===== 11. /current =====
@client.on(events.NewMessage(pattern="/current"))
async def current_cmd(event):
    user = get_user(event.sender_id)
    text = f"""**Current Settings**
Login: {user['logged_in']}
Watermark: {user['wm_text']}
WM Mode: {user['wm_mode']}
Zip Mode: {user['zip_mode']}
Delete Original: {user['delete']}
Filename: {user['filename']}"""
    await event.reply(text)

# ===== 12. /cancel =====
@client.on(events.NewMessage(pattern="/cancel"))
async def cancel_cmd(event):
    user_id = event.sender_id
    if user_id in zip_queue:
        for file in zip_queue[user_id]: os.remove(file)
        del zip_queue[user_id]
    await event.reply("✅ All videos cancelled")

# ===== VIDEO HANDLER =====
@client.on(events.NewMessage(func=lambda e: e.video))
async def handle_video(event):
    user_id = event.sender_id
    user = get_user(user_id)
    if not user["logged_in"]:
        await event.reply("Pehle /login karo")
        return

    if user["zip_mode"]:
        file_path = await event.download_media()
        if user_id not in zip_queue: zip_queue[user_id] = []
        if len(zip_queue[user_id]) >= MAX_ZIP_VIDEOS:
            await event.reply(f"Max {MAX_ZIP_VIDEOS} videos reached")
            return
        zip_queue[user_id].append(file_path)
        total = len(zip_queue[user_id])
        msg = await event.reply(f"📦 Added to Zip Queue\nTotal: {total}/{MAX_ZIP_VIDEOS} videos\nMode: {user['wm_text']}\n/zipnow = Foran zip")
        if user_id not in zip_queue_messages: zip_queue_messages[user_id] = []
        zip_queue_messages[user_id].append(msg.id)
    else:
        q_no = queue.qsize() + 1
        msg = await event.reply(f"⏳ Queue #{q_no}\nMode: {user['wm_text']}\n")
        queue_messages[event.id] = msg.id
        await queue.put((event, user_id))

async def worker():
    while True:
        event, user_id = await queue.get()
        async with semaphore:
            try:
                settings = get_user(user_id)
                output_file = await event.download_media() # yahan tumhara WM remove code
                sent_video = await client.send_file(user_id, output_file, caption=f"✅ {settings['wm_text']} Done")
                if event.id in queue_messages:
                    await client.delete_messages(user_id, queue_messages[event.id])
                    del queue_messages[event.id]
                await asyncio.sleep(2)
                await client.delete_messages(user_id, sent_video.id)
                os.remove(output_file)
            except Exception as e:
                await client.send_message(user_id, f"❌ Error: {e}")
            finally:
                queue.task_done()

async def main():
    asyncio.create_task(worker())
    print("Bot Started with All 12 Commands...")
    await client.run_until_disconnected()

with client:
    client.loop.run_until_complete(main())