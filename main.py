import os
import asyncio
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import subprocess

# Railway Variables se sab kuch utha rahe hain
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")
WATERMARK = os.environ.get("WATERMARK", "@WasiXD")
FONT_FILE = os.environ.get("FONT_FILE", "DejaVuSans.ttf")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
BOT_ID = int(os.environ.get("BOT_ID"))

# Session file Railway pe ban jayegi
client = TelegramClient('bot_session', API_ID, API_HASH)

# Queue for 1-by-1 processing
queue = asyncio.Queue()
processing = False
AUTHORIZED_USERS = set()

@client.on(events.NewMessage(pattern='/login'))
async def login_handler(event):
    if len(event.text.split()) < 2:
        await event.reply('Password bhi bhejo: `/login Wasi123`')
        return

    if event.text.split()[1] == BOT_PASSWORD:
        AUTHORIZED_USERS.add(event.sender_id)
        await event.reply('✅ Login successful! Ab video bhejo.')
    else:
        await event.reply('❌ Galat password.')

@client.on(events.NewMessage(func=lambda e: e.video or e.document))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS:
        await event.reply('Pehle /login karo password ke saath.')
        return

    await queue.put(event)
    pos = queue.qsize()
    await event.reply(f'📥 Video queue me add ho gayi. Position: {pos}')

    global processing
    if not processing:
        await process_queue()

async def process_queue():
    global processing
    processing = True

    while not queue.empty():
        event = await queue.get()
        try:
            await event.reply('⚙️ Processing start...')

            # Download video
            file = await event.download_media()

            # Watermark lagao ffmpeg se
            output_file = f"watermarked_{os.path.basename(file)}"
            cmd = [
                'ffmpeg', '-i', file,
                '-vf', f"drawtext=text='{WATERMARK}':fontfile={FONT_FILE}:fontsize=24:fontcolor=white@0.8:x=w-tw-10:y=h-th-10",
                '-c:a', 'copy', '-preset', 'ultrafast', output_file
            ]
            subprocess.run(cmd, check=True)

            # Upload karo
            await client.send_file(
                event.chat_id,
                output_file,
                caption=f'✅ Done | {WATERMARK}',
                reply_to=event.id
            )

            # Files delete karo
            os.remove(file)
            os.remove(output_file)

        except Exception as e:
            await event.reply(f'❌ Error: {str(e)}')
        finally:
            queue.task_done()

    processing = False

async def main():
    await client.start()
    print("✅ Bot Online! Telegram me /login password bhejo")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
