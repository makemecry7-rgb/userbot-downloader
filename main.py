import os
import re
import math
import shutil
import subprocess
import asyncio
import base64
import requests
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
COOKIES_FILE = "cookies.txt"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB

GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

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
    return [
        os.path.join(DOWNLOAD_DIR, f)
        for f in os.listdir(DOWNLOAD_DIR)
        if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))
    ]

def faststart(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-map", "0", "-c", "copy", "-movflags", "+faststart", fixed],
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

# ================= THUMBNAIL (FIXED) =================

def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"

    try:
        duration = float(subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            video
        ]).decode().strip())
        seek = max(1, int(duration // 2))
    except Exception:
        seek = 1

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(seek),
            "-i", video,
            "-vframes", "1",
            "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
            "-q:v", "5",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not os.path.exists(thumb):
        return None

    if os.path.getsize(thumb) > 200 * 1024:
        os.remove(thumb)
        return None

    return thumb

# ================= GOFILE (ADDED) =================

def is_gofile(url):
    return "gofile.io/d/" in url

def get_gofile_files(content_id):
    if not GOFILE_API_TOKEN:
        raise Exception("GOFILE_API_TOKEN not set")

    # 1. Get the dynamic API server (Required for uploads/downloads)
    s = requests.get("https://api.gofile.io/getServer", timeout=15).json()
    if s.get("status") != "ok":
        raise Exception("Failed to get GoFile server")
    server = s["data"]["server"]

    # 2. Call getContent - Ensure you use the specific account-based headers
    # Note: This endpoint now requires a Premium account as of 2025/2026.
    r = requests.get(
        f"api.gofile.io{content_id}",
        headers={
            "Authorization": f"Bearer {GOFILE_API_TOKEN}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        },
        timeout=30
    )

    if r.status_code == 404:
        raise Exception("GoFile link not found or content is private")
    if r.status_code == 429:
        raise Exception("Rate limit exceeded - GoFile enforces strict limits in 2026")
    if r.status_code != 200:
        raise Exception(f"GoFile HTTP {r.status_code}: {r.text}")

    data = r.json()
    if data.get("status") != "ok":
        # Handle the specific 'premium_only' error common in 2026
        error_msg = data.get("error", "Unknown API error")
        raise Exception(f"GoFile API error: {error_msg}")

    # 3. Extract direct links from the 'children' or 'contents' object
    files = []
    contents = data["data"].get("children", data["data"].get("contents", {}))
    
    for item_id, item in contents.items():
        if item.get("type") == "file":
            # directLink is valid but may require the Bearer token to download
            files.append((item["name"], item["directLink"]))

    if not files:
        raise Exception("No files found or folder is empty")

    return files
    





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
            await status_msg.edit(
                "⬇️ **Downloading**\n\n"
                f"`{text}`"
            )

    if await process.wait() != 0:
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

        # ---------- GOFILE ----------
        if is_gofile(url):
            content_id = url.rstrip("/").split("/")[-1]
            files = get_gofile_files(content_id)

            for name, link in files:
                out = os.path.join(DOWNLOAD_DIR, name)
                subprocess.run(["curl", "-L", link, "-o", out], check=True)

        # ---------- EVERYTHING ELSE ----------
        else:
            await ytdlp_download(url, status)

        files = collect_files()
        if not files:
            raise Exception("No files downloaded")

        await status.edit("📦 Processing video...")

        for f in files:
            fixed = faststart(f)
            thumb = generate_thumb(fixed)

            parts = (
                [fixed]
                if os.path.getsize(fixed) < SPLIT_SIZE
                else split_file(fixed)
            )

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

            if thumb and os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= RUN =================

app.run()
