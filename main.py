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
user_settings = {} # login, wm_mode, delete etc yahan save hoga

@client.on(events.NewMessage(pattern="/help"))
async def help_cmd(event):
    text = """**WMark Bot Commands**
/login - Login to bot
/logout - Logout from bot
/set - Set watermark text
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

@client.on(events.NewMessage(pattern="/current"))
async def current_cmd(event):
    await event.reply("Current Mode: No WM\nZip: OFF")

@client.on(events.NewMessage(pattern="/zipnow"))
async def make_zip(event):
    user_id = event.sender_id
    user = await client.get_entity(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"
    
    if user_id not in zip_queue or not zip_queue[user_id]:
        await client.send_message(user_id, "Zip queue is empty")
        return

    zip_name = f"Watermarked_{datetime.datetime.now().strftime('%d-%m-%Y_%H-%M')}.zip"
    with zipfile.ZipFile(zip_name, 'w') as zipf:
        for file in zip_queue[user_id]:
            zipf.write(file)
            os.remove(file)

    total = len(zip_queue[user_id])
    mode = "No WM"

    if user_id in zip_queue_messages:
        await client.delete_messages(user_id, zip_queue_messages[user_id])
        del zip_queue_messages[user_id]

    await client.send_file(user_id, zip_name, caption=f"📦 Zip Ready\nTotal: {total} videos\nMode: {mode}")
    
    # SIRF ZIP KA BACKUP
    if BACKUP_CHANNEL:
        caption = f"""📦 New Zip Backup
**User:** {username}  `ID: {user_id}`
**Total Videos:** {total}
**Mode:** {mode}
**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"""
        await client.send_file(BACKUP_CHANNEL, zip_name, caption=caption)

    del zip_queue[user_id]
    os.remove(zip_name)

print("Bot Started with Full Menu...")
client.run_until_disconnected()