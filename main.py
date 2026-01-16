import os
import re
import shutil
import subprocess
import requests
import time
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

TARGET_CHANNEL = -1003609000029  # YOUR CHANNEL

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB
UA = "Mozilla/5.0"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= PROGRESS =================

async def upload_progress(current, total, msg):
    if total == 0:
        return
    pct = current * 100 / total
    bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
    try:
        await msg.edit(f"⬆️ Uploading\n{bar}")
    except:
        pass

# ================= HELPERS =================

def extract_url(text):
    m = re.search(r"(https?://[^\s]+)", text)
    return m.group(1) if m else None

# ================= GOFILE =================

async def download_gofile(cid, status):
    r = requests.get(
        f"https://api.gofile.io/getContent?contentId={cid}",
        headers={"Authorization": f"Bearer {GOFILE_API_TOKEN}"}
    ).json()

    for f in r["data"]["children"].values():
        if f["type"] != "file":
            continue

        out = os.path.join(DOWNLOAD_DIR, f["name"])
        with requests.get(f["directLink"], stream=True) as d:
            total = int(d.headers.get("content-length", 0))
            cur = 0
            with open(out, "wb") as o:
                for chunk in d.iter_content(1024 * 1024):
                    o.write(chunk)
                    cur += len(chunk)
                    if total:
                        pct = cur * 100 / total
                        bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                        try:
                            await status.edit(f"⬇️ Downloading (GoFile)\n{bar}")
                        except:
                            pass

# ================= GENERIC / DIRECT / YTDLP =================

async def download_generic(url, status):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "-o", out,
        url
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    last = 0
    for line in proc.stdout:
        if "%" in line and time.time() - last > 1:
            last = time.time()
            try:
                pct = float(line.split("%")[0].split()[-1])
                bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                await status.edit(f"⬇️ Downloading\n{bar}")
            except:
                pass

    proc.wait()

# ================= SPLIT =================

def split_file(path):
    parts = []
    with open(path, "rb") as f:
        i = 1
        while True:
            chunk = f.read(SPLIT_SIZE)
            if not chunk:
                break
            part = f"{path}.part{i}.mp4"
            with open(part, "wb") as o:
                o.write(chunk)
            parts.append(part)
            i += 1
    os.remove(path)
    return parts

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting download...")

    try:
        if GOFILE_RE.search(url):
            await download_gofile(GOFILE_RE.search(url).group(1), status)
        else:
            await download_generic(url, status)

        await status.edit("⬆️ Uploading to channel...")

        for f in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, f)
            if not path.lower().endswith(ALLOWED_EXT):
                continue

            files = [path]
            if os.path.getsize(path) > SPLIT_SIZE:
                files = split_file(path)

            for part in files:
                await app.send_video(
                    TARGET_CHANNEL,
                    part,
                    supports_streaming=True,
                    progress=upload_progress,
                    progress_args=(status,)
                )
                os.remove(part)

    except Exception as e:
        await status.edit(f"❌ Error:\n{e}")

    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= START =================

app.run()
