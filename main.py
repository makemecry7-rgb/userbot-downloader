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
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN") # Required for folder listing

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"

# Modern 2026 headers for Bunkr and Cloudflare-protected sites
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Updated Regex for 2026 domains
PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(?:[a-z0-9]+\.)?bunkr\.(?:cr|pk|fi|ru|black|st|is)/")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= CLIENT =================

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# ================= HELPERS =================

def extract_clean_url(text):
    """Prevents 'URL Spotted!' recursion error by isolating the link."""
    match = re.search(r'(https?://[^\s\n]+)', text)
    return match.group(1) if match else None

def collect_files(root):
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            p = os.path.join(base, n)
            if any(p.lower().endswith(ext) for ext in ALLOWED_EXT):
                files.append(p)
    return files

# ---------- GOFILE DOWNLOADER ----------
def download_gofile(content_id):
    headers = {"Authorization": f"Bearer {GOFILE_API_TOKEN}", "User-Agent": UA}
    res = requests.get(f"api.gofile.io{content_id}", headers=headers)
    if res.status_code != 200:
        raise Exception(f"GoFile API {res.status_code}. Free accounts may be blocked.")
    
    data = res.json()
    contents = data["data"].get("children", data["data"].get("contents", {}))
    
    for item_id in contents:
        item = contents[item_id]
        if item["type"] == "file":
            # Use yt-dlp with cookies to handle the actual download/auth
            download_ytdlp(item["directLink"], os.path.join(DOWNLOAD_DIR, item["name"]))

# ---------- YT-DLP CORE ----------
def download_ytdlp(url, out_pattern):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", UA,
        "--add-header", f"Referer:{referer}",
        "--add-header", "Sec-Ch-Ua:\"Not_A Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "--merge-output-format", "mp4",
        "-o", out_pattern,
        url # Clean URL only
    ]
    subprocess.run(cmd, check=True)

# ---------- VIDEO PROCESSING ----------
def faststart_and_thumb(src):
    base_name = src.rsplit(".", 1)[0]
    fixed = f"{base_name}_fixed.mp4"
    thumb = f"{base_name}.jpg"

    subprocess.run(["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb], 
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    if os.path.exists(src): os.remove(src)
    return fixed, (thumb if os.path.exists(thumb) else None)

def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)
    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as o: o.write(f.read(SPLIT_SIZE))
            parts.append(part)
    os.remove(path)
    return parts

# ================= USERBOT HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_clean_url(m.text)
    if not url: return
    
    status = await m.reply("⏳ Processing...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if (gf := GOFILE_RE.search(url)):
            await status.edit("📁 GoFile detected. Fetching contents...")
            download_gofile(gf.group(1))
        elif (px := PIXELDRAIN_RE.search(url)):
            await status.edit("💧 Pixeldrain detected...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)
        elif MEGA_RE.search(url):
            await status.edit("☁️ MEGA detected...")
            subprocess.run(["megadl", "--path", DOWNLOAD_DIR, url], check=True)
        else:
            await status.edit("🎥 Extracting video...")
            out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
            download_ytdlp(url, out)

        files = collect_files(DOWNLOAD_DIR)
        if not files: raise Exception("No media found.")

        await status.edit(f"📦 Uploading {len(files)} files...")
        for f in files:
            fixed, thumb = faststart_and_thumb(f)
            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)
            for p in parts:
                await app.send_video("me", video=p, thumb=thumb, supports_streaming=True, 
                                     caption=f"`{os.path.basename(p)}`")
                if os.path.exists(p): os.remove(p)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        await status.edit("✅ Success")
    except Exception as e:
        await status.edit(f"❌ Error:\n`{str(e)}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

if __name__ == "__main__":
    app.run()
