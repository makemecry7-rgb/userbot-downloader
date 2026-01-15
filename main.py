import os
import shutil
import subprocess
import asyncio
import time
import base64

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
SPLIT_SIZE = 1900 * 1024 * 1024

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= COOKIES =================

if not os.path.exists(COOKIES_FILE):
    b64 = os.getenv("COOKIES_B64")
    if b64:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(b64))

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= MP4 FIX (REAL FIX) =================

def rebuild_mp4(src):
    fixed = src.replace(".mp4", "_rebuilt.mp4")

    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", src,
        "-map", "0",
        "-c:v", "copy",
        "-c:a", "copy",
        "-movflags", "+faststart",
        fixed
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if os.path.exists(fixed) and os.path.getsize(fixed) > 1_000_000:
        os.remove(src)
        return fixed

    if os.path.exists(fixed):
        os.remove(fixed)

    return src

# ================= SPLIT (SIZE SAFE) =================

def split_video(path):
    size = os.path.getsize(path)
    if size < SPLIT_SIZE:
        return [path]

    parts = []
    base = path.replace(".mp4", "")
    duration = float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of",
             "default=noprint_wrappers=1:nokey=1", path]
        ).decode().strip()
    )

    count = int(size / SPLIT_SIZE) + 1
    seg_time = int(duration / count)

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", path,
            "-map", "0",
            "-c", "copy",
            "-f", "segment",
            "-segment_time", str(seg_time),
            "-reset_timestamps", "1",
            f"{base}_part%02d.mp4"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    for f in sorted(os.listdir(DOWNLOAD_DIR)):
        if f.startswith(os.path.basename(base)) and "part" in f:
            parts.append(os.path.join(DOWNLOAD_DIR, f))

    os.remove(path)
    return parts

# ================= THUMBNAIL =================

def make_thumb(video):
    thumb = video.replace(".mp4", ".jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "5", "-i", video,
         "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb if os.path.exists(thumb) else None

# ================= DOWNLOADERS =================

async def aria2_download(url, status):
    cmd = [
        "aria2c",
        "--file-allocation=trunc",
        "-x", "8", "-s", "8",
        "-d", DOWNLOAD_DIR,
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        txt = line.decode(errors="ignore")
        if "%" in txt:
            await status.edit(f"⬇️ Downloading\n{txt.strip()}")

    if await proc.wait() != 0:
        raise Exception("aria2 failed")

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    if not url.startswith("http"):
        return

    status = await m.reply("⬇️ Starting download...")
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    try:
        await aria2_download(url, status)

        files = [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)]
        if not files:
            raise Exception("No file downloaded")

        for f in files:
            fixed = rebuild_mp4(f)
            parts = split_video(fixed)
            total = len(parts)

            for i, p in enumerate(parts, 1):
                thumb = make_thumb(p)
                await app.send_video(
                    "me",
                    p,
                    supports_streaming=True,
                    thumb=thumb,
                    caption=f"{os.path.basename(p)} ({i}/{total})"
                )
                os.remove(p)
                if thumb:
                    os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n{e}")

# ================= RUN =================

app.run()
