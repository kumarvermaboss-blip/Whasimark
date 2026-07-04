import asyncio
import os
import datetime
from telethon import TelegramClient, events

# ========== CONFIG ==========
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
MAX_ZIP_VIDEOS = int(os.environ.get("MAX_ZIP_VIDEOS", "10"))
BACKUP_CHANNEL = os.environ.get("BACKUP_CHANNEL", None) # Railway me set karo

semaphore = asyncio.Semaphore(MAX_CONCURRENT)
queue = asyncio.Queue()
queue_messages = {} 
zip_queue_messages = {} 
zip_queue = {} # user_id: [list of files]

# ... tumhara client start ...

async def worker():
    while True:
        event, user_id = await queue.get()
        async with semaphore:
            try:
                output_file = await process_video(event) # tumhara watermark remove function

                # 1. User ko video bhejo
                sent_video = await client.send_file(user_id, output_file, caption="✅ No WM Done")
                
                # 2. Queue wala msg delete
                if event.id in queue_messages:
                    await client.delete_messages(user_id, queue_messages[event.id])
                    del queue_messages[event.id]
                
                # 3. 2 sec baad video wala msg bhi delete
                await asyncio.sleep(2)
                await client.delete_messages(user_id, sent_video.id)
                os.remove(output_file)

            except Exception as e:
                await client.send_message(user_id, f"❌ Error: {e}")
            finally:
                queue.task_done()

@client.on(events.NewMessage(func=lambda e: e.video))
async def handle_video(event):
    user_id = event.sender_id
    q_no = queue.qsize() + 1
    msg = await client.send_message(user_id, f"⏳ Queue #{q_no}\nMode: No WM\n")
    queue_messages[event.id] = msg.id
    await queue.put((event, user_id))

# ========== ZIP WALA HISSA ==========
@client.on(events.NewMessage(pattern="/zip"))
async def add_to_zip(event):
    user_id = event.sender_id
    
    if user_id not in zip_queue:
        zip_queue[user_id] = []
    
    if len(zip_queue[user_id]) >= MAX_ZIP_VIDEOS:
        await client.send_message(user_id, f"Max {MAX_ZIP_VIDEOS} videos reached")
        return

    zip_queue[user_id].append(event.media) # file save karo

    total = len(zip_queue[user_id])
    msg = await client.send_message(user_id, f"📦 Added to Zip Queue\nTotal: {total}/{MAX_ZIP_VIDEOS} videos\nMode: No WM\n/zipnow = Foran zip")
    if user_id not in zip_queue_messages:
        zip_queue_messages[user_id] = []
    zip_queue_messages[user_id].append(msg.id)

@client.on(events.NewMessage(pattern="/zipnow"))
async def make_zip(event):
    user_id = event.sender_id
    user = await client.get_entity(user_id)
    username = f"@{user.username}" if user.username else f"{user.first_name}"
    
    if user_id not in zip_queue or not zip_queue[user_id]:
        await client.send_message(user_id, "Zip queue is empty")
        return

    # ... yahan tum zip banate ho ...
    zip_path = "Watermarked.zip" 
    total = len(zip_queue[user_id])
    mode = "No WM"

    # 1. User ke purane zip msgs delete
    if user_id in zip_queue_messages:
        await client.delete_messages(user_id, zip_queue_messages[user_id])
        del zip_queue_messages[user_id]

    # 2. User ko zip bhejo
    await client.send_file(user_id, zip_path, caption=f"📦 Zip Ready\nTotal: {total} videos\nMode: {mode}")
    
    # 3. SIRF YAHAN CHANNEL ME BACKUP + CAPTION
    if BACKUP_CHANNEL:
        try:
            caption = f"""📦 New Zip Backup
**User:** {username}  `ID: {user_id}`
**Total Videos:** {total}
**Mode:** {mode}
**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"""
            await client.send_file(BACKUP_CHANNEL, zip_path, caption=caption)
            print(f"Backup sent to channel for {user_id}")
        except Exception as e:
            print(f"Channel backup error: {e}")

    del zip_queue[user_id]
    os.remove(zip_path) # local file delete