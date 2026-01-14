import os
import re
import math
import time
import asyncio
import subprocess

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

# ============ CONFIG ============
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION = os.getenv("SESSION", "userbot")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ============ REGEX ============
MEGA_RE = re.compile(r"https?://mega\.nz/")
URL_RE = re.compile(r"https?://")

# ============ UTILS ============

def human(n):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f}{unit}"
        n /= 1024
    return "∞"

def progress_bar(done, total):
    if total == 0:
        return "▱" * 10
    percent = done / total
    filled = int(percent * 10)
    return "▰" * filled + "▱" * (10 - filled)

async def edit_progress(msg, text):
    try:
        await msg.edit(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except:
        pass

# ============ THUMB + FASTSTART ============

def faststart_and_thumb(src):
    base, _ = os.path.splitext(src)
    fixed = base + "_fixed.mp4"
    thumb = base + ".jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:02", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if os.path.exists(src):
        os.remove(src)

    if not os.path.exists(thumb):
        thumb = None

    return fixed, thumb

# ============ YT-DLP DOWNLOAD ============

async def ytdlp_download(url, msg):
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--merge-output-format", "mp4",
        "--newline",
        "-o", f"{DOWNLOAD_DIR}/%(title)s.%(ext)s",
        url
    ]

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    last_update = time.time()

    for line in process.stdout:
        if "[download]" in line and "%" in line:
            try:
                percent = float(line.split("%")[0].split()[-1])
                bar = progress_bar(percent, 100)
                if time.time() - last_update > 1.2:
                    await edit_progress(
                        msg,
                        f"⬇️ **Downloading**\n{bar} `{percent:.2f}%`"
                    )
                    last_update = time.time()
            except:
                pass

    process.wait()
    if process.returncode != 0:
        raise Exception("yt-dlp failed")

# ============ MEGA DOWNLOAD ============

async def mega_download(url, msg):
    cmd = ["mega-get", "--ignore-quota-warn", "--recursive", url, DOWNLOAD_DIR]

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    last_update = time.time()

    for line in process.stdout:
        if "%" in line:
            try:
                percent = float(line.split("%")[0].strip())
                bar = progress_bar(percent, 100)
                if time.time() - last_update > 1.5:
                    await edit_progress(
                        msg,
                        f"⬇️ **Downloading from MEGA**\n{bar} `{percent:.2f}%`"
                    )
                    last_update = time.time()
            except:
                pass

    process.wait()
    if process.returncode != 0:
        raise Exception("MEGA download failed")

# ============ SEND FILES ============

async def send_all(app, msg):
    for root, _, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            path = os.path.join(root, f)

            if f.lower().endswith(".mp4"):
                fixed, thumb = faststart_and_thumb(path)

                kwargs = dict(
                    chat_id="me",
                    video=fixed,
                    supports_streaming=True,
                    caption=os.path.basename(fixed)
                )
                if thumb:
                    kwargs["thumb"] = thumb

                await app.send_video(**kwargs)

                os.remove(fixed)
                if thumb and os.path.exists(thumb):
                    os.remove(thumb)

            else:
                await app.send_document("me", path)
                os.remove(path)

# ============ BOT ============

app = Client(SESSION, api_id=API_ID, api_hash=API_HASH)

@app.on_message(filters.me & filters.text)
async def handler(_, message: Message):
    text = message.text.strip()

    if not URL_RE.search(text):
        return

    status = await message.reply("🔄 **Starting download...**")

    try:
        if MEGA_RE.search(text):
            await mega_download(text, status)
        else:
            await ytdlp_download(text, status)

        await edit_progress(status, "📤 **Uploading...**")
        await send_all(app, status)

        await status.edit("✅ **Done! Sent to Saved Messages**")

    except Exception as e:
        await status.edit(f"❌ **Failed**\n`{e}`")

app.run()
