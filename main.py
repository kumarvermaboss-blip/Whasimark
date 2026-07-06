import os
import re
import time
import asyncio
from telethon import TelegramClient, events, Button
import zipfile
import shutil

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_PASSWORD = os.environ.get("BOT_PASSWORD")

WATERMARK = os.environ.get("WATERMARK", "@bvsrv1")
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "1"))
MAX_SIZE_MB = 180

client = TelegramClient('bot_session', API_ID, API_HASH)

queue = asyncio.Queue()
processing = set()
semaphore = asyncio.Semaphore(MAX_CONCURRENT)
cancel_flags = {}
AUTHORIZED_USERS = set()
PENDING_STATES = {}
queue_messages = {}
ZIP_QUEUE = []
last_edit = {}

CURRENT_WATERMARK = WATERMARK
CURRENT_COLOR = "red@1"
DELETE_ORIGINAL = False
NAME_MODE = "water_id"
CUSTOM_PREFIX = "wm_"
WATERMARK_MODE = "bouncing"
ZIP_MODE = False
NO_WM_MODE = False
WM_PERCENT = 0.05

async def worker():
    while True:
        event, user_id = await queue.get()
        async with semaphore:
            if event.id in cancel_flags or user_id in cancel_flags:
                cancel_flags.pop(event.id, None)
                cancel_flags.pop(user_id, None)
                queue.task_done()
                continue
            processing.add(event.id)
            try:
                await process_video(event, user_id)
            except Exception as e:
                print(f"WORKER ERROR: {e}")
            finally:
                processing.discard(event.id)
                cancel_flags.pop(event.id, None)
                queue.task_done()

async def progress_callback(current, total, msg, action, event_id, user_id):
    if event_id in cancel_flags or user_id in cancel_flags:
        raise asyncio.CancelledError("Cancelled by user")
    percent = int(current * 100 / total)
    now = time.time()
    if (percent % 20 == 0 or percent == 100) and (now - last_edit.get(msg.id, 0) > 3):
        last_edit[msg.id] = now
        try: await msg.edit(f"{action} {percent}%")
        except: pass

async def process_video(event, user_id):
    global ZIP_QUEUE
    msg = None
    file = None
    output = None
    try:
        q_pos = queue.qsize() + len(processing)
        msg = await client.send_message(user_id, f"⏳ **Queue #{q_pos}**")
        queue_messages[event.id] = msg.id

        file = await event.download_media(progress_callback=lambda c, t: progress_callback(c, t, msg, "📥 Downloading", event.id, user_id))
        if event.id in cancel_flags or user_id in cancel_flags: raise asyncio.CancelledError("Cancelled")

        if NAME_MODE == "original":
            output = event.file.name if event.file and event.file.name else f"video_{event.id}.mp4"
        elif NAME_MODE == "custom":
            output = f"{CUSTOM_PREFIX}{event.file.name}" if event.file and event.file.name else f"{CUSTOM_PREFIX}video_{event.id}.mp4"
        else:
            output = f"water_{event.id}.mp4"

        safe_watermark = CURRENT_WATERMARK.replace("'", "\\'").replace(":", "\\:").replace("%", "%%")
        original_size_mb = os.path.getsize(file) / (1024*1024)
        needs_compress = original_size_mb > 80

        if NO_WM_MODE:
            await msg.edit("📦 **No Watermark Mode**")
            shutil.copy(file, output)
        else:
            probe_cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', file]
            probe = await asyncio.create_subprocess_exec(*probe_cmd, stdout=asyncio.subprocess.PIPE)
            stdout, _ = await probe.communicate()
            w, h = map(int, stdout.decode().strip().split('x'))

            file_for_wm = file
            temp_file = None

            if needs_compress:
                await msg.edit(f"🗜️ **Step 1/2: Compressing to 720p...** `{original_size_mb:.1f}MB`")
                temp_file = f"temp_{event.id}.mp4"
                cmd1 = ['ffmpeg', '-threads', '1', '-i', file, '-vf', f"scale=-2:720", '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26', '-maxrate', '2M', '-bufsize', '4M', '-c:a', 'aac', '-b:a', '96k', temp_file, '-y']
                proc1 = await asyncio.create_subprocess_exec(*cmd1, stderr=asyncio.subprocess.PIPE)
                _, _ = await proc1.communicate()
                if proc1.returncode!= 0: raise Exception("FFmpeg Step 1 Error")
                file_for_wm = temp_file
                probe_cmd2 = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=s=x:p=0', temp_file]
                probe2 = await asyncio.create_subprocess_exec(*probe_cmd2, stdout=asyncio.subprocess.PIPE)
                stdout2, _ = await probe2.communicate()
                w, h = map(int, stdout2.decode().strip().split('x'))

            await msg.edit("🎬 **Step 2/2: Watermark laga rahe...**")
            dynamic_size = int(w * WM_PERCENT)
            final_size = max(20, min(150, dynamic_size))
            text_w = final_size * 0.5 * len(safe_watermark)
            margin = int(w * 0.02)
            max_x = max(margin, w - text_w - margin)
            max_y = max(margin, h - final_size - margin)

            if WATERMARK_MODE == "bouncing":
                speed_x = w / 10
                speed_y = h / 12
                x_formula = f"min(max({margin}\\,mod({speed_x}*t\\,{max_x}))\\,{max_x})"
                y_formula = f"min(max({margin}\\,mod({speed_y}*t\\,{max_y}))\\,{max_y})"
            else:
                x_formula = f"{margin}"
                y_formula = f"{margin}"

            vf_filter = f"drawtext=fontfile=./DejaVuSans.ttf:text='{safe_watermark}':fontsize={final_size}:fontcolor={CURRENT_COLOR}:x='{x_formula}':y='{y_formula}'"
            crf_val = '26' if needs_compress else '24'
            cmd2 = ['ffmpeg', '-threads', '1', '-i', file_for_wm, '-vf', vf_filter, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', crf_val, '-c:a', 'copy', output, '-y']
            proc2 = await asyncio.create_subprocess_exec(*cmd2, stderr=asyncio.subprocess.PIPE)
            _, _ = await proc2.communicate()
            if proc2.returncode!= 0: raise Exception("FFmpeg Step 2 Error")
            if temp_file and os.path.exists(temp_file): os.remove(temp_file)

        if ZIP_MODE:
            ZIP_QUEUE.append(output)
            await event.reply(f"📦 **Added to Zip Queue**\nTotal: `{len(ZIP_QUEUE)}`")
        else:
            if event.id in queue_messages: await client.delete_messages(user_id, queue_messages[event.id])
            final_size_mb = os.path.getsize(output) / (1024*1024)
            await client.send_file(event.chat_id, output, caption=f"✅ Done | Size: `{original_size_mb:.1f}MB` > `{final_size_mb:.1f}MB`", reply_to=event.id, force_document=True, progress_callback=lambda c, t: progress_callback(c, t, msg, "📤 Uploading", event.id, user_id))
            await msg.delete()
            if os.path.exists(output): os.remove(output)
        if DELETE_ORIGINAL: await event.delete()

    except asyncio.CancelledError:
        if msg: await msg.edit("🚫 Cancelled by user")
    except Exception as e:
        if msg: await msg.edit(f"❌ Failed: {e}")
    finally:
        try:
            if file and os.path.exists(file): os.remove(file)
        except: pass

# ===== WIZARD + COMMANDS v2.25.11b =====
@client.on(events.NewMessage(pattern=r'^/start'))
async def start_handler(event):
    buttons = [
        [Button.inline('🔑 Bot Login', b'login'), Button.inline('🔒 Logout', b'logout')],
        [Button.inline('📊 Current Settings', b'current'), Button.inline('📖 Help', b'help')],
        [Button.inline('✏️ Set WM Text', b'set'), Button.inline('🎨 Set Color', b'color')],
        [Button.inline('📐 WM Size %', b'wmpercent'), Button.inline('🔄 WM Mode', b'wmmode')],
        [Button.inline('🚫 No WM', b'nowm'), Button.inline('🗑️ Delete Orig', b'delete')],
        [Button.inline('📝 File Name', b'setname'), Button.inline('📦 Zip Mode', b'zip')],
        [Button.inline('⬇️ Create Zip', b'zipnow'), Button.inline('❌ Cancel Queue', b'cancel_menu')]
    ]
    await event.reply('**WMark Bot v2.25.11b**\nNeeche se setting select karo:', buttons=buttons)

@client.on(events.CallbackQuery)
async def callback_handler(event):
    data = event.data.decode('utf-8')
    user_id = event.sender_id
    global WATERMARK_MODE, NO_WM_MODE, DELETE_ORIGINAL, ZIP_MODE, CURRENT_WATERMARK, CURRENT_COLOR, WM_PERCENT, NAME_MODE, CUSTOM_PREFIX

    if data == 'login': await event.respond('🔑 Password bhejo: `/login password`')
    elif data == 'logout': AUTHORIZED_USERS.discard(user_id); await event.respond('✅ Logged Out')
    elif data == 'current': await event.respond(f"Current Settings:\nWM: {CURRENT_WATERMARK}\nColor: {CURRENT_COLOR}\nMode: {WATERMARK_MODE}\nSize%: {WM_PERCENT}\nZip: {ZIP_MODE}\nNoWM: {NO_WM_MODE}\nDelete: {DELETE_ORIGINAL}\nName: {NAME_MODE}")
    elif data == 'help': await event.respond("Commands:\n/login pass /logout /current\n/set text /color red@1 /wmpercent 0.05\n/wmmode /nowm /delete /setname mode\n/zip /zipnow /cancel /cancel all /cancel 1")
    elif data == 'cancel_menu': await show_cancel_menu(event, user_id)
    elif data.startswith('cancel_'):
        action = data.split('_')[1]
        await handle_cancel_action(event, user_id, action)
    elif data == 'set': PENDING_STATES[user_id] = 'set'; await event.respond('Please enter watermark text')
    elif data == 'color': PENDING_STATES[user_id] = 'color'; await event.respond('Color Examples:\nred@1 = Red\nwhite@1 = White\nyellow@0.9 = Yellow 90%')
    elif data == 'wmpercent': PENDING_STATES[user_id] = 'wmpercent'; await event.respond('Enter size percentage: 0.03 to 0.08')
    elif data == 'wmmode': WATERMARK_MODE = 'static' if WATERMARK_MODE=='bouncing' else 'bouncing'; await event.respond(f'WM Mode: {WATERMARK_MODE}')
    elif data == 'nowm': NO_WM_MODE = not NO_WM_MODE; await event.respond(f'NoWM: {NO_WM_MODE}')
    elif data == 'delete': PENDING_STATES[user_id] = 'delete'; await event.respond('Enter on or off')
    elif data == 'setname': PENDING_STATES[user_id] = 'setname'; await event.respond('Enter: original / custom / water_id')
    elif data == 'zip': ZIP_MODE = not ZIP_MODE; await event.respond(f'Zip: {ZIP_MODE}')
    elif data == 'zipnow': await zip_handler(event)
    await event.answer()

async def show_cancel_menu(event, user_id):
    buttons = []
    if processing:
        buttons.append([Button.inline('❌ Current Video', b'cancel_current')])
    if not queue.empty():
        q_list = list(queue._queue)
        for i in range(min(len(q_list), 5)):
            buttons.append([Button.inline(f'🚫 Cancel Queue #{i+1}', f'cancel_q_{i+1}'.encode())])
    if processing or not queue.empty():
        buttons.append([Button.inline('🔥 Cancel ALL', b'cancel_all')])
    if not buttons:
        await event.respond("🚫 Cancel karne ke liye kuch nahi hai")
        return
    await event.respond("**Kya Cancel karna hai?**", buttons=buttons)

async def handle_cancel_action(event, user_id, action):
    if action == 'current':
        cancel_flags[user_id] = True
        for pid in list(processing): cancel_flags[pid] = True
        await event.respond("🚫 Current video cancelled")
    elif action == 'all':
        cancel_flags[user_id] = True
        for pid in list(processing): cancel_flags[pid] = True
        while not queue.empty(): await queue.get()
        await event.respond("🚫 All Cancelled")
    elif action.startswith('q_'):
        num = int(action.split('_')[1])
        temp_queue = asyncio.Queue()
        skipped = False
        found_pos = 0
        while not queue.empty():
            e, uid = await queue.get()
            found_pos += 1
            if found_pos == num and not skipped:
                await event.respond(f"🚫 Queue #{num} skip kar di")
                skipped = True
                queue.task_done()
                continue
            await temp_queue.put((e, uid))
        while not temp_queue.empty(): await queue.put(await temp_queue.get())

@client.on(events.NewMessage)
async def pending_handler(event):
    user_id = event.sender_id
    if user_id in PENDING_STATES:
        state = PENDING_STATES.pop(user_id)
        text = event.text
        global CURRENT_WATERMARK, WM_PERCENT, NAME_MODE, CUSTOM_PREFIX, CURRENT_COLOR, DELETE_ORIGINAL
        if state == 'set': CURRENT_WATERMARK = text; await event.reply(f'✅ Watermark Updated\n{text}')
        elif state == 'color': CURRENT_COLOR = text; await event.reply(f'✅ Watermark Color: {text}')
        elif state == 'wmpercent': WM_PERCENT = float(text); await event.reply(f'WM Size%: {text}')
        elif state == 'setname': NAME_MODE = text; CUSTOM_PREFIX = "wm_" if text=="custom" else ""; await event.reply(f'Name: {text}')
        elif state == 'delete': DELETE_ORIGINAL = text.lower() == 'on'; await event.reply(f'Delete: {DELETE_ORIGINAL}')

@client.on(events.NewMessage(pattern=r'^/help'))
async def help_handler(event): await event.reply("Commands:\n/login pass /logout /current\n/set text /color red@1 /wmpercent 0.05\n/wmmode /nowm /delete /setname mode\n/zip /zipnow /cancel /cancel all /cancel 1")

@client.on(events.NewMessage(pattern=r'^/current'))
async def current_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    await event.reply(f"Current Settings:\nWM: {CURRENT_WATERMARK}\nColor: {CURRENT_COLOR}\nMode: {WATERMARK_MODE}\nSize%: {WM_PERCENT}\nZip: {ZIP_MODE}\nNoWM: {NO_WM_MODE}\nDelete: {DELETE_ORIGINAL}\nName: {NAME_MODE}")

@client.on(events.NewMessage(pattern=r'^/login (.+)'))
async def login_handler(event):
    if event.text.split(maxsplit=1)[1] == BOT_PASSWORD: AUTHORIZED_USERS.add(event.sender_id); await event.reply('✅ Login Success!')
    else: await event.reply('❌ Wrong password.')

@client.on(events.NewMessage(pattern=r'^/logout'))
async def logout_handler(event): AUTHORIZED_USERS.discard(event.sender_id); await event.reply('✅ Logged Out')

@client.on(events.NewMessage(pattern=r'^/set (.+)'))
async def set_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global CURRENT_WATERMARK; CURRENT_WATERMARK = event.text.split(maxsplit=1)[1]; await event.reply(f'✅ Watermark Updated\n{CURRENT_WATERMARK}')

@client.on(events.NewMessage(pattern=r'^/set$'))
async def set_no_arg(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    PENDING_STATES[event.sender_id] = 'set'; await event.reply('Please enter watermark text')

@client.on(events.NewMessage(pattern=r'^/color (.+)'))
async def color_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global CURRENT_COLOR; CURRENT_COLOR = event.text.split(maxsplit=1)[1]; await event.reply(f'✅ Watermark Color: {CURRENT_COLOR}')

@client.on(events.NewMessage(pattern=r'^/color$'))
async def color_no_arg(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    await event.reply('Color Examples:\nred@1 = Red\nwhite@1 = White\nyellow@0.9 = Yellow 90%')

@client.on(events.NewMessage(pattern=r'^/wmpercent (.+)'))
async def wmpercent_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global WM_PERCENT; WM_PERCENT = float(event.text.split(maxsplit=1)[1]); await event.reply(f'WM Size%: {WM_PERCENT}')

@client.on(events.NewMessage(pattern=r'^/wmmode'))
async def wmmode_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global WATERMARK_MODE; WATERMARK_MODE = 'static' if WATERMARK_MODE=='bouncing' else 'bouncing'; await event.reply(f'WM Mode: {WATERMARK_MODE}')

@client.on(events.NewMessage(pattern=r'^/nowm'))
async def nowm_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global NO_WM_MODE; NO_WM_MODE = not NO_WM_MODE; await event.reply(f'NoWM: {NO_WM_MODE}')

@client.on(events.NewMessage(pattern=r'^/delete$'))
async def delete_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    PENDING_STATES[event.sender_id] = 'delete'; await event.reply('Enter on or off')

@client.on(events.NewMessage(pattern=r'^/delete (on|off)'))
async def delete_direct(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global DELETE_ORIGINAL; DELETE_ORIGINAL = event.text.split()[1] == 'on'; await event.reply(f'Delete: {DELETE_ORIGINAL}')

@client.on(events.NewMessage(pattern=r'^/setname (.+)'))
async def setname_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global NAME_MODE, CUSTOM_PREFIX; NAME_MODE = event.text.split(maxsplit=1)[1]; CUSTOM_PREFIX = "wm_" if NAME_MODE=="custom" else ""; await event.reply(f'Name: {NAME_MODE}')

@client.on(events.NewMessage(pattern=r'^/zip'))
async def zip_toggle_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return
    global ZIP_MODE; ZIP_MODE = not ZIP_MODE; await event.reply(f'Zip: {ZIP_MODE}')

@client.on(events.NewMessage(pattern=r'^/cancel(?:\s+(all|\d+))?$'))
async def cancel_handler(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 /login password')
    match = re.match(r'^/cancel(?:\s+(all|\d+))?$', event.text)
    arg = match.group(1)
    if arg == 'all':
        cancel_flags[event.sender_id] = True
        for pid in list(processing): cancel_flags[pid] = True
        while not queue.empty(): await queue.get()
        await event.reply("🚫 All Cancelled")
    elif arg and arg.isdigit():
        num = int(arg)
        temp_queue = asyncio.Queue()
        skipped = False
        found_pos = 0
        while not queue.empty():
            e, uid = await queue.get()
            found_pos += 1
            if found_pos == num and not skipped:
                await event.reply(f"🚫 Queue #{num} skip kar di")
                skipped = True
                queue.task_done()
                continue
            await temp_queue.put((e, uid))
        while not temp_queue.empty(): await queue.put(await temp_queue.get())
        if not skipped: await event.reply(f"Queue #{num} nahi mili")
    else:
        await show_cancel_menu(event, event.sender_id)

@client.on(events.NewMessage(pattern=r'^/zipnow'))
async def zip_handler(event):
    if not ZIP_QUEUE: return await event.reply("Zip queue is empty")
    zip_name = f"zip_{event.id}.zip"
    with zipfile.ZipFile(zip_name, 'w') as zipf:
        for f in ZIP_QUEUE: zipf.write(f, os.path.basename(f))
    await client.send_file(event.chat_id, zip_name)
    for f in ZIP_QUEUE: os.remove(f)
    ZIP_QUEUE.clear()
    os.remove(zip_name)
    await event.reply("✅ Zip sent")

@client.on(events.NewMessage(func=lambda e: e.video or (e.document and e.document.mime_type and e.document.mime_type.startswith('video/'))))
async def handle_video(event):
    if event.sender_id not in AUTHORIZED_USERS: return await event.reply('🔒 /login password')
    if event.file and event.file.size > MAX_SIZE_MB * 1024 * 1024:
        return await event.reply(f"🚫 Video too large\nSize: `{event.file.size / (1024*1024):.1f}MB`\nLimit: `{MAX_SIZE_MB}MB`")
    await queue.put((event, event.sender_id))

async def main():
    for _ in range(MAX_CONCURRENT): asyncio.create_task(worker())
    await client.start(bot_token=BOT_TOKEN)
    print("✅ Bot Online v2.25.11b")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())