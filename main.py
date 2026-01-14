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

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)", re.I)
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)", re.I)
MEGA_RE = re.compile(r"https?://mega\.nz/", re.I)
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.", re.I)

# ================= COOKIES =================

def ensure_cookies():
    if os.path.exists(COOKIES_FILE):
        return
    b64 = os.getenv("COOKIES_B64")
    if b64:
        with open(COOKIES_FILE, "wb") as f:
            f.write(base64.b64decode(b64))

ensure_cookies()

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= HELPERS =================

def collect_files(root):
    out = []
    for b, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(b, f)
            if p.lower().endswith(ALLOWED_EXT):
                out.append(p)
    return out

def normalize_mega(url):
    return url.split("/folder/")[0]

# ================= DOWNLOADERS =================

def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

def download_gofile_public(fid):
    r = requests.get(
        f"https://api.gofile.io/contents/{fid}",
        params={"wt": "4fd6sg89d7s6"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "ok":
        raise Exception("GoFile blocked")

    for info in data["data"]["contents"].values():
        if info["type"] != "file":
            continue
        if not info["name"].lower().endswith(ALLOWED_EXT):
            continue

        path = os.path.join(DOWNLOAD_DIR, info["name"])
        with requests.get(info["link"], stream=True) as d:
            d.raise_for_status()
            with open(path, "wb") as f:
                for c in d.iter_content(1024 * 1024):
                    if c:
                        f.write(c)

def download_mega(url):
    subprocess.run(
        ["megadl", "--recursive", "--path", DOWNLOAD_DIR, normalize_mega(url)],
        check=True
    )

def download_ytdlp(url, out):
    p = urlparse(url)
    ref = f"{p.scheme}://{p.netloc}/"
    subprocess.run([
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0",
        "--add-header", f"Referer:{ref}",
        "--add-header", f"Origin:{ref}",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ], check=True)

# ================= VIDEO FIX =================

def faststart_and_thumb(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    thumb = src.rsplit(".", 1)[0] + ".jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "1", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    os.remove(src)
    return fixed, thumb

def split_file(path):
    parts = []
    with open(path, "rb") as f:
        i = 1
        while True:
            chunk = f.read(SPLIT_SIZE)
            if not chunk:
                break
            p = f"{path}.part{i}.mp4"
            with open(p, "wb") as o:
                o.write(chunk)
            parts.append(p)
            i += 1
    os.remove(path)
    return parts

# ================= HANDLER =================

@app.on_message(filters.text)
async def handler(_, m: Message):
    text = (m.text or "").strip()
    if not text.startswith("http"):
        return

    status = await m.reply("🔍 Processing link...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if BUNKR_RE.search(text):
            await status.edit("❌ Bunkr blocked")
            return

        if (px := PIXELDRAIN_RE.search(text)):
            await status.edit("⬇️ Pixeldrain")
            info = requests.get(
                f"https://pixeldrain.com/api/file/{px.group(1)}/info"
            ).json()
            download_pixeldrain(px.group(1), os.path.join(DOWNLOAD_DIR, info["name"]))

        elif (gf := GOFILE_RE.search(text)):
            await status.edit("⬇️ GoFile")
            download_gofile_public(gf.group(1))

        elif MEGA_RE.search(text):
            await status.edit("⬇️ MEGA")
            download_mega(text)

        else:
            await status.edit("🎥 yt-dlp")
            download_ytdlp(text, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("Nothing downloaded")

        await status.edit("📦 Uploading...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)
            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True
                )
                os.remove(p)

            if os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

app.run()
