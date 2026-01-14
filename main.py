import os
import re
import math
import time
import shutil
import base64
import asyncio
import subprocess
from urllib.parse import urlparse

import requests
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.")

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

edit_lock = asyncio.Lock()

# ================= SAFE MESSAGE EDIT =================

async def safe_edit(msg, text):
    async with edit_lock:
        try:
            if msg.text != text:
                await msg.edit(text)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass

# ================= HELPERS =================

def collect_files():
    out = []
    for root, _, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            if f.lower().endswith(ALLOWED_EXT):
                out.append(os.path.join(root, f))
    return out

def progress_bar(done, total):
    if total == 0:
        return "⬜⬜⬜⬜⬜ 0%"
    pct = done / total * 100
    bars = int(pct / 10)
    return "🟩" * bars + "⬜" * (10 - bars) + f" {pct:.1f}%"

# ================= PIXELDRAIN =================

def download_pixeldrain(fid, path, cb):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    total = int(r.headers.get("content-length", 0))
    done = 0
    with open(path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                cb(done, total)

# ================= YT-DLP =================

def download_ytdlp(url, out, cb):
    last = time.time()

    def hook(d):
        nonlocal last
        if d["status"] == "downloading":
            if time.time() - last > 2.5:
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                cb(done, total)
                last = time.time()

    cmd = [
        "yt-dlp",
        "--cookies", COOKIES_FILE,
        "--no-playlist",
        "--merge-output-format", "mp4",
        "-o", out,
        url,
        "--progress",
        "--newline",
        "--progress-template", "%(downloaded_bytes)s/%(total_bytes)s",
        "--no-warnings"
    ]

    subprocess.run(cmd, check=True)

# ================= MEGA =================

def download_mega(url, cb):
    last = time.time()

    proc = subprocess.Popen(
        ["megadl", "--recursive", "--path", DOWNLOAD_DIR, url],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    for line in proc.stdout:
        if time.time() - last > 3:
            cb(1, 1)
            last = time.time()

    if proc.wait() != 0:
        raise Exception("MEGA download failed")

# ================= VIDEO FIX =================

def faststart_and_thumb(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    thumb = src.rsplit(".", 1)[0] + ".jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not os.path.exists(thumb):
        thumb = None

    os.remove(src)
    return fixed, thumb

# ================= SPLIT =================

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

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        def progress(done, total):
            asyncio.create_task(
                safe_edit(
                    status,
                    f"⬇️ Downloading...\n{progress_bar(done, total)}"
                )
            )

        if BUNKR_RE.search(url):
            await safe_edit(status, "❌ Bunkr blocked")
            return

        if (px := PIXELDRAIN_RE.search(url)):
            info = requests.get(
                f"https://pixeldrain.com/api/file/{px.group(1)}/info"
            ).json()
            path = os.path.join(DOWNLOAD_DIR, info["name"])
            download_pixeldrain(px.group(1), path, progress)

        elif MEGA_RE.search(url):
            await safe_edit(status, "⬇️ Downloading from MEGA...")
            download_mega(url, progress)

        else:
            out = os.path.join(DOWNLOAD_DIR, "%(title).80s.%(ext)s")
            download_ytdlp(url, out, progress)

        files = collect_files()
        if not files:
            raise Exception("No video found")

        await safe_edit(status, f"📦 Uploading {len(files)} file(s)...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)

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

        await safe_edit(status, "✅ Done")

    except Exception as e:
        await safe_edit(status, f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= RUN =================

app.run()
