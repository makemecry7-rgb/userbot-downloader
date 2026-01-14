import os
import re
import math
import shutil
import subprocess
import asyncio
import base64
from urllib.parse import urlparse

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

def ensure_cookies():
    if os.path.exists(COOKIES_FILE):
        return
    data = os.getenv("COOKIES_B64")
    if data:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(data))

ensure_cookies()

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= HELPERS =================

def collect_files():
    files = []
    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(p):
            files.append(p)
    return files

def faststart(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(src)
    return fixed

def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(part)

    os.remove(path)
    return parts

# ================= YT-DLP WITH PROGRESS =================

async def ytdlp_download(url, status_msg):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last_edit = 0

    while True:
        line = await process.stdout.readline()
        if not line:
            break

        text = line.decode(errors="ignore").strip()

        if "[download]" in text and "%" in text:
            now = asyncio.get_event_loop().time()
            if now - last_edit < 1.2:
                continue
            last_edit = now

            # example line:
            # [download]  34.5% of 120.43MiB at 2.34MiB/s ETA 00:51
            await status_msg.edit(
                "⬇️ **Downloading**\n\n"
                f"`{text}`"
            )

    code = await process.wait()
    if code != 0:
        raise Exception("yt-dlp failed")

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = (m.text or "").strip()
    if not url.startswith("http"):
        return

    status = await m.reply("🔍 Detecting video...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        await ytdlp_download(url, status)

        files = collect_files()
        if not files:
            raise Exception("No files downloaded")

        await status.edit("📦 Processing video...")

        for f in files:
            fixed = faststart(f)

            parts = (
                [fixed]
                if os.path.getsize(fixed) < SPLIT_SIZE
                else split_file(fixed)
            )

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
