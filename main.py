import os
import re
import math
import shutil
import subprocess
import requests
import base64
import json
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

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.")

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
    files = []
    for b, _, names in os.walk(root):
        for n in names:
            p = os.path.join(b, n)
            if p.lower().endswith(ALLOWED_EXT):
                files.append(p)
    return files

# ================= PIXELDRAIN =================

def download_pixeldrain(fid, path):
    r = requests.get(
        f"https://pixeldrain.com/api/file/{fid}",
        stream=True,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ================= GOFILE (PUBLIC BYPASS) =================

def download_gofile_public(folder_id):
    page = requests.get(
        f"https://gofile.io/d/{folder_id}",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    page.raise_for_status()

    # Extract embedded JSON
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", page.text)
    if not m:
        raise Exception("Failed to parse GoFile page")

    data = json.loads(m.group(1))
    contents = data["content"]["children"]

    for f in contents.values():
        if f["type"] != "file":
            continue

        name = f["name"]
        if not name.lower().endswith(ALLOWED_EXT):
            continue

        url = f["link"]
        path = os.path.join(DOWNLOAD_DIR, name)

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(path, "wb") as o:
                for c in r.iter_content(1024 * 1024):
                    if c:
                        o.write(c)

# ================= MEGA =================

def download_mega(url):
    subprocess.run(
        ["megadl", "--recursive", "--path", DOWNLOAD_DIR, url],
        check=True,
    )

# ================= YT-DLP (UNCHANGED) =================

def download_ytdlp(url, out):
    parsed = urlparse(url)
    ref = f"{parsed.scheme}://{parsed.netloc}/"

    subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--cookies",
            COOKIES_FILE,
            "--user-agent",
            "Mozilla/5.0",
            "--add-header",
            f"Referer:{ref}",
            "--add-header",
            f"Origin:{ref}",
            "--merge-output-format",
            "mp4",
            "-o",
            out,
            url,
        ],
        check=True,
    )

# ================= STREAM FIX =================

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
            p = f"{path}.part{i+1}.mp4"
            with open(p, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(p)

    os.remove(path)
    return parts

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    text = (m.text or "").strip()
    if not text.startswith("http"):
        return

    status = await m.reply("🔍 Processing...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if BUNKR_RE.search(text):
            await status.edit("❌ Bunkr blocked on Railway")
            return

        if (px := PIXELDRAIN_RE.search(text)):
            await status.edit("⬇️ Pixeldrain...")
            info = requests.get(
                f"https://pixeldrain.com/api/file/{px.group(1)}/info"
            ).json()
            download_pixeldrain(px.group(1), os.path.join(DOWNLOAD_DIR, info["name"]))

        elif (gf := GOFILE_RE.search(text)):
            await status.edit("⬇️ GoFile...")
            download_gofile_public(gf.group(1))

        elif MEGA_RE.search(text):
            await status.edit("⬇️ MEGA...")
            download_mega(text)

        else:
            await status.edit("🎥 yt-dlp...")
            download_ytdlp(text, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No video files found")

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
