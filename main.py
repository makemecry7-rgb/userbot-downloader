import os
import re
import time
import math
import shutil
import requests
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://gofile.io/",
}

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= UTILS =================

def download_requests(url, path):
    r = requests.get(url, stream=True, headers=HEADERS, timeout=20)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

def download_ytdlp(url, path):
    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", path,
        url
    ]
    subprocess.run(cmd, check=True)

def download_aria2(url, path):
    cmd = [
        "aria2c",
        "-x", "8",
        "-s", "8",
        "-o", os.path.basename(path),
        "-d", os.path.dirname(path),
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
    return dst

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

def get_gofile_files(cid):
    r = requests.get(
        f"https://api.gofile.io/contents/{cid}",
        headers=HEADERS,
        timeout=15
    )
    if not r.text.startswith("{"):
        raise Exception("API blocked")
    data = r.json()
    if data.get("status") != "ok":
        raise Exception("API restricted")
    return [
        {"name": f["name"], "url": f["link"]}
        for f in data["data"]["children"].values()
        if f["type"] == "file"
    ]

# ================= BOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    text = m.text.strip()
    px = PIXELDRAIN_RE.search(text)
    gf = GOFILE_RE.search(text)

    if not px and not gf:
        return

    status = await m.reply("🔍 Processing...")

    try:
        files = []

        if px:
            fid = px.group(1)
            info = requests.get(f"https://pixeldrain.com/api/file/{fid}/info").json()
            files = [{
                "name": info["name"],
                "url": f"https://pixeldrain.com/api/file/{fid}"
            }]
        else:
            files = get_gofile_files(gf.group(1))

        for f in files:
            name = f["name"]
            path = os.path.join(DOWNLOAD_DIR, name)

            await status.edit("⬇️ Trying direct download…")
            try:
                download_requests(f["url"], path)
            except:
                await status.edit("⚠️ Direct failed → yt-dlp")
                try:
                    download_ytdlp(f["url"], path)
                except:
                    await status.edit("⚠️ yt-dlp failed → aria2")
                    download_aria2(f["url"], path)

            if not path.lower().endswith(".mp4"):
                path = convert_mp4(path)

            parts = [path] if os.path.getsize(path) < SPLIT_SIZE else split_file(path)

            for p in parts:
                await m.reply_video(p, supports_streaming=True)
                os.remove(p)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Failed:\n`{e}`")
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
