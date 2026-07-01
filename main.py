from telethon import TelegramClient, events
import asyncio
import os
from config import API_ID, API_HASH, WATERMARK, FONT_FILE, MAX_CONCURRENT

# Railway ke liye env vars se lo
BOT_ID = int(os.environ.get("BOT_ID", 8037023119))
BOT_PASSWORD = os.environ.get("BOT_PASSWORD", "Wasi123")

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
authorized_users = set()

CURRENT_WATERMARK = os.environ.get("WATERMARK", WATERMARK)
CURRENT_COLOR = "red@0.5"
DELETE_ORIGINAL = False

client = TelegramClient('userbot_session', API_ID, API_HASH)

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
    if percent % 10 == 0 or percent == 100: # 5% se 10% kar diya - kam edits
        try:
            await msg.edit(f"{action} {percent}%")
        except:
            pass

async def process_video(event):
    msg = await event.reply(f"⏳ Queue #{len(processing)} Starting...")
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

        # SPEED BOOST: ultrafast + crf 28 + threads
        cmd = [
            'ffmpeg', '-i', file,
            '-vf', f"scale=1280:-2,drawtext=text='{CURRENT_WATERMARK}':fontfile={FONT_FILE}:fontsize=h/25:x=(w-text_w)/2:y=(h-text_h)/2:fontcolor={CURRENT_COLOR}",
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-c:a', 'copy', '-threads', '4',
            output, '-y'
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
            caption="",
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

@client.on(events.NewMessage)
async def handler(event):
    global CURRENT_WATERMARK, CURRENT_COLOR, DELETE_ORIGINAL

    if not event.is_private: # BOT_ID check hata diya - kisi bhi chat me kaam karega
        return

    # LOGIN
    if event.text and event.text.startswith('/login '):
        password = event.text[7:].strip()
        if password == BOT_PASSWORD:
            authorized_users.add(event.sender_id)
            await event.reply("✅ **Login Success!**\n\nAb tum bot use kar sakte ho.\n`/help` likho commands ke liye.")
        else:
            await event.reply("❌ **Wrong Password!**")
        return

    # LOGOUT
    if event.text == '/logout':
        if event.sender_id in authorized_users:
            authorized_users.remove(event.sender_id)
            await event.reply("✅ **Logged Out!**\nBot ab lock hai.")
        else:
            await event.reply("❌ Tum login hi nahi ho")
        return

    # AUTH CHECK
    if event.sender_id not in authorized_users:
        await event.reply("🔒 **Bot Locked**\n\nPassword daalo: `/login your_password`")
        return

    # SET WATERMARK
    if event.text and event.text.startswith('/set '):
        new_wm = event.text[5:].strip()
        if new_wm:
            CURRENT_WATERMARK = new_wm
            await event.reply(f"✅ **Watermark Updated**\n`{new_wm}`")
        else:
            await event.reply("❌ **Usage:** `/set @YourText`")
        return

    # SET COLOR
    if event.text and event.text.startswith('/color '):
        new_color = event.text[7:].strip()
        if new_color:
            CURRENT_COLOR = new_color
            await event.reply(f"✅ **Color Updated**\n`{new_color}`\n\n**Examples:**\n`red@1.0` - Dark solid\n`white@0.3` - Light transparent")
        else:
            await event.reply("❌ **Usage:** `/color white@0.5` ya `/color red`")
        return

    # DELETE ORIGINAL TOGGLE
    if event.text and event.text.startswith('/delete '):
        mode = event.text[8:].strip().lower()
        if mode == 'on':
            DELETE_ORIGINAL = True
            await event.reply("✅ **Delete Original: ON**\nAb original videos delete ho jayengi")
        elif mode == 'off':
            DELETE_ORIGINAL = False
            await event.reply("✅ **Delete Original: OFF**\nOriginal videos save rahengi")
        else:
            await event.reply("❌ **Usage:** `/delete on` ya `/delete off`")
        return

    # DARK MODE
    if event.text == '/dark':
        CURRENT_COLOR = "white@0.8"
        await event.reply("✅ **Dark Mode ON**\nColor: `white@0.8`")
        return

    # LIGHT MODE
    if event.text == '/light':
        CURRENT_COLOR = "white@0.3"
        await event.reply("✅ **Light Mode ON**\nColor: `white@0.3`")
        return

    # CURRENT SETTINGS
    if event.text == '/current':
        await event.reply(
            f"**📊 Current Settings:**\n\n"
            f"**Watermark:** `{CURRENT_WATERMARK}`\n"
            f"**Color:** `{CURRENT_COLOR}`\n"
            f"**Delete Original:** `{DELETE_ORIGINAL}`\n"
            f"**Max Concurrent:** `{MAX_CONCURRENT}`\n"
            f"**Queue:** `{queue.qsize()}` | **Processing:** `{len(processing)}`"
        )
        return

    # CANCEL ALL
    if event.text == '/cancel' and not event.is_reply:
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
        return

    # CANCEL SPECIFIC
    if event.text == '/cancel' and event.is_reply:
        reply_msg = await event.get_reply_message()
        cancel_flags[reply_msg.id] = True
        await event.reply("🚫 **Cancelling this video...**")
        return

    # HELP
    if event.text == '/help' or event.text == '/start':
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
        return

    # VIDEO PROCESS
    if not (event.video or (event.document and event.document.mime_type and event.document.mime_type.startswith('video/'))):
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

    await client.start()
    print("✅ Bot Online! Telegram me /login password bhejo")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
