import os
import re
import math
import shutil
import subprocess
import requests
import base64
import time
import asyncio
from urllib.parse import urlparse

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
    skip_updates=True
)

# ================= HELPERS =================

edit_lock = asyncio.Lock()

async def safe_edit(msg, text):
    async with edit_lock:
        try:
            if msg.text != text:
                await msg.edit(text)
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except Exception:
            pass

def collect_files():
    out = []
    for b, _, f in os.walk(DOWNLOAD_DIR):
        for n in f:
            p = os.path.join(b, n)
            if p.lower().endswith(ALLOWED_EXT):
                out.append(p)
    return out

# ---------- PIXELDRAIN ----------
def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ---------- MEGA ----------
def download_mega(url):
    subprocess.run(
        ["megadl", "--recursive", "--path", DOWNLOAD_DIR, url],
        check=True
    )

# ---------- YT-DLP ----------
async def download_ytdlp(url, out, status):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0",
        "--referer", referer,
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )

    last = time.time()
    async for line in proc.stdout:
        line = line.decode()
        if "[download]" in line and "%" in line:
            if time.time() - last > 2.5:
                await safe_edit(status, f"⬇️ {line.strip()}")
                last = time.time()

    if await proc.wait() != 0:
        raise Exception("yt-dlp failed")

# ---------- FIX STREAMING + AV1 THUMB ----------
def faststart_and_thumb(src):
    base, _ = os.path.splitext(src)
    fixed = base + "_fixed.mp4"
    thumb = base + ".jpg"

    # Faststart copy
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # AV1-safe thumbnail (re-encode ONE frame)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", fixed,
            "-ss", "00:00:02",
            "-frames:v", "1",
            "-q:v", "2",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    os.remove(src)

    if not os.path.exists(thumb):
        thumb = None

    return fixed, thumb

# ---------- SPLIT ----------
def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            p = f"{path}.part{i+1}.mp4"
            with open(p, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(p)

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

        if BUNKR_RE.search(url):
            await safe_edit(status, "❌ Bunkr blocked")
            return

        if (px := PIXELDRAIN_RE.search(url)):
            await safe_edit(status, "⬇️ Pixeldrain...")
            info = requests.get(f"https://pixeldrain.com/api/file/{px.group(1)}/info").json()
            download_pixeldrain(px.group(1), os.path.join(DOWNLOAD_DIR, info["name"]))

        elif MEGA_RE.search(url):
            await safe_edit(status, "⬇️ MEGA...")
            download_mega(url)

        else:
            await safe_edit(status, "🎥 Downloading video...")
            await download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title).80s.%(ext)s"), status)

        files = collect_files()
        if not files:
            raise Exception("No video found")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)
            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)

            for p in parts:
                kwargs = dict(
                    chat_id="me",
                    video=p,
                    supports_streaming=True,
                    caption=os.path.basename(p)
                )
                if thumb:
                    kwargs["thumb"] = thumb

                await app.send_video(**kwargs)
                os.remove(p)

            if thumb and os.path.exists(thumb):
                os.remove(thumb)

        await safe_edit(status, "✅ Done")

    except Exception as e:
        await safe_edit(status, f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= START =================

app.run()
