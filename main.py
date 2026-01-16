import os, re, math, shutil, subprocess, requests, time
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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= PROGRESS =================

async def upload_progress(current, total, msg):
    pct = current * 100 / total if total else 0
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
                for c in d.iter_content(1024*1024):
                    o.write(c)
                    cur += len(c)
                    pct = cur * 100 / total if total else 0
                    bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                    try:
                        await status.edit(f"⬇️ Downloading (GoFile)\n{bar}")
                    except:
                        pass

# ================= MEGA =================

async def download_mega(url, status):
    cmd = [
        "megadl",
        "--recursive",
        "--path", DOWNLOAD_DIR,
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
        if "%" in line and time.time() - last > 2:
            last = time.time()
            try:
                pct = float(line.split("%")[0].split()[-1])
                bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                await status.edit(f"⬇️ Downloading (MEGA)\n{bar}")
            except:
                pass

    proc.wait()

# ================= YTDLP + ARIA2 =================

async def download_with_aria2(url, status):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--downloader", "aria2c",
        "--downloader-args", "aria2c:-x16 -s16 -k1M",
        "--cookies", COOKIES_FILE,
        "--user-agent", UA,
        "--merge-output-format", "mp4",
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
        if "%" in line and time.time() - last > 2:
            last = time.time()
            try:
                pct = float(line.split("%")[0].split()[-1])
                bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                await status.edit(f"⬇️ Downloading\n{bar}")
            except:
                pass

    proc.wait()

# ================= VIDEO FIX =================

def fix_video(src):
    base = src.rsplit(".", 1)[0]
    fixed = f"{base}_fixed.mp4"
    thumb = f"{base}.jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:10", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb if os.path.exists(thumb) else None

# ================= SPLIT =================

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

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting...")

    if GOFILE_RE.search(url):
        await download_gofile(GOFILE_RE.search(url).group(1), status)

    elif MEGA_RE.search(url):
        await download_mega(url, status)

    else:
        await download_with_aria2(url, status)

    await status.edit("🎞 Processing...")

    for f in os.listdir(DOWNLOAD_DIR):
        p = os.path.join(DOWNLOAD_DIR, f)
        if not p.lower().endswith(ALLOWED_EXT):
            continue

        fixed, thumb = fix_video(p)
        files = [fixed]

        if os.path.getsize(fixed) > SPLIT_SIZE:
            files = split_file(fixed)

        for part in files:
            await app.send_video(
                m.chat.id,
                part,
                thumb=thumb,
                supports_streaming=True,
                progress=upload_progress,
                progress_args=(status,)
            )
            os.remove(part)

        if thumb and os.path.exists(thumb):
            os.remove(thumb)

    shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================= START =================

app.run()
