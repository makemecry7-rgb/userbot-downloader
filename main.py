import os, re, math, shutil, subprocess, requests, time, base64
from urllib.parse import urlparse
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN") 

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024
COOKIES_FILE = "cookies.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= PROGRESS BAR HELPERS =================

_progress_data = {}

def get_pb(current, total):
    percent = (current / total) * 100 if total else 0
    done = int(percent / 10)
    return f"[{'█' * done}{'░' * (10 - done)}] {percent:.1f}%"

async def progress_func(current, total, message, tag):
    now = time.time()
    key = id(message)

    if key not in _progress_data:
        _progress_data[key] = now

    start = _progress_data[key]
    elapsed = max(now - start, 1)
    speed = current / elapsed
    eta = (total - current) / speed if speed > 0 else 0

    if not hasattr(progress_func, "last"):
        progress_func.last = 0
    if now - progress_func.last < 3:
        return
    progress_func.last = now

    bar = get_pb(current, total)

    try:
        await message.edit(
            f"**{tag}**\n{bar}\n"
            f"`{current/1024/1024:.2f} / {total/1024/1024:.2f} MB`\n"
            f"🚀 `{speed/1024/1024:.2f} MB/s` | ⏳ `{int(eta)}s`"
        )
    except:
        pass

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    sleep_threshold=60
)

# ================= HELPERS =================

def extract_clean_url(text):
    m = re.search(r'(https?://[^\s]+)', text)
    return m.group(1) if m else None

# ---------- GOFILE DOWNLOADER ----------
async def download_gofile(content_id, status_msg):
    headers = {
        "Authorization": f"Bearer {GOFILE_API_TOKEN}",
        "User-Agent": UA
    }

    res = requests.get(
        f"https://api.gofile.io/getContent?contentId={content_id}",
        headers=headers
    )
    data = res.json()["data"]["children"]

    for item in data.values():
        if item["type"] != "file":
            continue

        out = os.path.join(DOWNLOAD_DIR, item["name"])

        with requests.get(item["directLink"], stream=True) as r:
            total = int(r.headers.get("content-length", 0))
            cur = 0
            with open(out, "wb") as f:
                for c in r.iter_content(1024 * 1024):
                    f.write(c)
                    cur += len(c)
                    await progress_func(cur, total, status_msg, "Downloading")

# ---------- YT-DLP ----------
def download_ytdlp(url, out):
    parsed = urlparse(url)
    subprocess.run([
        "yt-dlp",
        "--no-playlist",
        "--cookies", COOKIES_FILE,
        "--user-agent", UA,
        "--add-header", f"Referer:{parsed.scheme}://{parsed.netloc}/",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ], check=True)

# ---------- VIDEO FIX + THUMB ----------
def faststart_and_thumb(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # 🔥 ONLY CHANGE: thumbnail at 1 minute
    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:01:00", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb if os.path.exists(thumb) else None

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
async def handler(client, m: Message):
    url = extract_clean_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting download...")

    if GOFILE_RE.search(url):
        cid = GOFILE_RE.search(url).group(1)
        await download_gofile(cid, status)
    else:
        download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))

    await status.edit("🎞 Processing video...")

    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)
        if not p.lower().endswith(ALLOWED_EXT):
            continue

        fixed, thumb = faststart_and_thumb(p)
        parts = [fixed]

        if os.path.getsize(fixed) > SPLIT_SIZE:
            parts = split_file(fixed)

        for part in parts:
            await client.send_video(
                chat_id=m.chat.id,
                video=part,
                thumb=thumb,
                supports_streaming=True,
                progress=progress_func,
                progress_args=("Uploading", status)
            )
            os.remove(part)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= START =================

app.run()
