import os
import re
import time
import math
import shutil
import requests
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# =============== CONFIG ===============

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB safe

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Referer": "https://gofile.io/",
}

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# =============== HELPERS ===============

def human(size):
    for u in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{u}"
        size /= 1024
    return f"{size:.2f}TB"


def download_with_progress(url, path, msg):
    r = requests.get(url, stream=True, headers=HEADERS)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    done = 0
    last = time.time()

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)

                if time.time() - last > 2:
                    pct = (done / total * 100) if total else 0
                    msg.edit_text(
                        f"📥 Downloading\n{pct:.1f}% | {human(done)}/{human(total)}"
                    )
                    last = time.time()


def convert_to_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


def extract_thumbnail(video):
    thumb = video + ".jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-i", video, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return thumb


def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as p:
                p.write(f.read(SPLIT_SIZE))
            parts.append(part)

    os.remove(path)
    return parts


def get_gofile_files(content_id):
    url = f"https://api.gofile.io/contents/{content_id}"

    r = requests.get(url, headers=HEADERS, timeout=20)

    if not r.text.strip().startswith("{"):
        raise Exception("Gofile blocked request (HTML / empty response)")

    data = r.json()

    if data.get("status") != "ok":
        raise Exception("Gofile API error or restricted link")

    files = []
    for item in data["data"]["children"].values():
        if item.get("type") == "file":
            files.append({
                "name": item["name"],
                "url": item["link"],
            })

    if not files:
        raise Exception("No downloadable files found")

    return files

# =============== BOT ===============

@app.on_message(filters.private & filters.text)
async def handler(client: Client, message: Message):
    text = message.text.strip()

    px = PIXELDRAIN_RE.search(text)
    gf = GOFILE_RE.search(text)

    if not px and not gf:
        return

    status = await message.reply("🔍 Fetching info...")

    try:
        files = []

        if px:
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()
            files.append({
                "name": info["name"],
                "url": f"https://pixeldrain.com/api/file/{fid}",
            })
        else:
            cid = gf.group(1)
            files = get_gofile_files(cid)

        for item in files:
            name = item["name"]
            path = os.path.join(DOWNLOAD_DIR, name)

            await status.edit_text(f"📥 Downloading\n{name}")
            download_with_progress(item["url"], path, status)

            if not path.lower().endswith(".mp4"):
                await status.edit_text("🎬 Converting to MP4")
                new = convert_to_mp4(path)
                os.remove(path)
                path = new

            parts = (
                split_file(path)
                if os.path.getsize(path) > SPLIT_SIZE
                else [path]
            )

            for i, part in enumerate(parts, 1):
                await status.edit_text(f"📤 Uploading part {i}/{len(parts)}")
                thumb = extract_thumbnail(part)

                await message.reply_video(
                    video=part,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=os.path.basename(part),
                )

                os.remove(thumb)
                os.remove(part)

        await status.edit_text("✅ Done & cleaned")

    except Exception as e:
        await status.edit_text(f"❌ Error:\n`{e}`")
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
