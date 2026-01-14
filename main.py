import os
import re
import math
import shutil
import subprocess
import requests
import base64
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

ALLOWED_EXT = (
    ".mp4", ".mkv", ".webm", ".avi", ".mov",
    ".jpg", ".jpeg", ".png", ".webp"
)

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.(cr|pk|fi|ru)/")

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

def collect_files(root):
    result = []
    for base, _, files in os.walk(root):
        for f in files:
            path = os.path.join(base, f)
            if path.lower().endswith(ALLOWED_EXT):
                result.append(path)
    return result

def is_direct_video(url):
    return url.lower().split("?")[0].endswith(
        (".mp4", ".mkv", ".webm", ".avi", ".mov")
    )

def is_hls(url):
    return ".m3u8" in url.lower()

# ---------- ARIA2 ----------
def download_aria2(url, out):
    cmd = [
        "aria2c",
        "-x", "1",
        "-s", "1",
        "-k", "1M",
        "--timeout=20",
        "--connect-timeout=20",
        "--file-allocation=trunc",
        "--header=User-Agent: Mozilla/5.0",
        "-o", out,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- DIRECT ----------
def download_direct(url, path):
    r = requests.get(url, stream=True, timeout=(10, 30))
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

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
    cmd = [
        "megadl",
        "--recursive",
        "--path", DOWNLOAD_DIR,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- YT-DLP ----------
def download_ytdlp(url, out):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0",
        "--add-header", f"Referer:{referer}",
        "--add-header", f"Origin:{referer}",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]
    subprocess.run(cmd, check=True)

# ---------- CONVERT ----------
def convert_mp4(src):
    if src.lower().endswith(".mp4"):
        return src
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(src)
    return dst

# ---------- SPLIT ----------
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

# ================= USERBOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Detecting link type...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # ❌ BUNKR
        if BUNKR_RE.search(url):
            await status.edit(
                "❌ **Bunkr blocked on Railway**\n"
                "Use local VPS to download bunkr."
            )
            return

        # MEGA
        if MEGA_RE.search(url):
            await status.edit("⬇️ Downloading from MEGA...")
            download_mega(url)

        # PIXELDRAIN
        elif (px := PIXELDRAIN_RE.search(url)):
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()
            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading from Pixeldrain...")
            download_pixeldrain(fid, path)

        # DIRECT VIDEO
        elif is_direct_video(url):
            name = url.split("/")[-1].split("?")[0]
            path = os.path.join(DOWNLOAD_DIR, name)
            await status.edit("⚡ Direct downloading...")
            try:
                download_aria2(url, path)
            except Exception:
                download_direct(url, path)

        # HLS / OTHER
        else:
            await status.edit("🎥 Extracting via yt-dlp...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

        # COLLECT FILES
        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No media files found")

        await status.edit(f"📦 Uploading {len(files)} files...")

        # UPLOAD
        for f in files:
            path = convert_mp4(f)
            parts = (
                [path]
                if os.path.getsize(path) < SPLIT_SIZE
                else split_file(path)
            )

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

        await status.edit("✅ Done & cleaned")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
