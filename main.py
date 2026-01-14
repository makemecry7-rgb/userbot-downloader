import os
import re
import math
import shutil
import subprocess
import requests
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= HELPERS =================

def is_direct_video(url):
    return url.lower().split("?")[0].endswith(
        (".mp4", ".mkv", ".webm", ".avi", ".mov")
    )

def is_hls(url):
    return ".m3u8" in url.lower()

def download_direct(url, path):
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)

def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

def download_ytdlp(url, out):
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]
    subprocess.run(cmd, check=True)

def convert_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(src)
    return dst

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

# ================= BOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Detecting link type...")

    try:
        files = []

        # ---------- PIXELDRAIN ----------
        px = PIXELDRAIN_RE.search(url)
        if px:
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()

            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading from Pixeldrain")
            download_pixeldrain(fid, path)
            files.append(path)

        # ---------- DIRECT VIDEO ----------
        elif is_direct_video(url):
            filename = url.split("/")[-1].split("?")[0]
            path = os.path.join(DOWNLOAD_DIR, filename)

            await status.edit("⬇️ Direct video download")
            download_direct(url, path)
            files.append(path)

        # ---------- HLS / M3U8 ----------
        elif is_hls(url):
            await status.edit("📡 Downloading HLS stream")
            out = os.path.join(DOWNLOAD_DIR, "video.%(ext)s")
            download_ytdlp(url, out)

            for f in os.listdir(DOWNLOAD_DIR):
                files.append(os.path.join(DOWNLOAD_DIR, f))

        # ---------- WEB PAGE ----------
        else:
            await status.edit("🎥 Extracting via yt-dlp")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

            for f in os.listdir(DOWNLOAD_DIR):
                files.append(os.path.join(DOWNLOAD_DIR, f))

        # ---------- PROCESS ----------
        for f in files:
            path = f

            if not path.lower().endswith(".mp4"):
                path = convert_mp4(path)

            parts = (
                [path]
                if os.path.getsize(path) < SPLIT_SIZE
                else split_file(path)
            )

            for p in parts:
                await m.reply_video(
                    video=p,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

        await status.edit("✅ Completed & cleaned")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
