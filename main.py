import os, re, subprocess, time, threading
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

LOG_CHANNEL = -1003609000029  # YOUR CHANNEL

TMP_DIR = "/tmp"
UA = "Mozilla/5.0"

ALLOWED_VIDEO = (".mp4", ".mkv", ".webm", ".mov", ".avi")

# ================= CLIENT =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
)

# ================= KEEP RAILWAY ALIVE =================

def heartbeat():
    while True:
        print("alive")
        time.sleep(60)

threading.Thread(target=heartbeat, daemon=True).start()

# ================= HELPERS =================

def extract_url(text):
    m = re.search(r"(https?://[^\s]+)", text)
    return m.group(1) if m else None

async def log(text):
    try:
        await app.send_message(LOG_CHANNEL, text)
    except:
        pass

async def upload_progress(current, total, msg):
    if total == 0:
        return
    pct = current * 100 / total
    bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
    try:
        await msg.edit(f"⬆️ Uploading\n{bar}")
    except:
        pass

# ================= DOWNLOAD =================

async def download_video(url, status):
    await log(f"⬇️ Download started\n{url}")

    out = os.path.join(TMP_DIR, "video.%(ext)s")

    cmd = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--user-agent", UA,
        "-f", "bv*+ba/b",
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

    for f in os.listdir(TMP_DIR):
        if f.lower().endswith(ALLOWED_VIDEO):
            return os.path.join(TMP_DIR, f)

    return None

# ================= FIX STREAMING + THUMB =================

def fix_video(src):
    fixed = src.replace(".", "_fixed.", 1)
    thumb = src.replace(".", ".jpg", 1)

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:05", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb if os.path.exists(thumb) else None

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting...")

    try:
        video = await download_video(url, status)
        if not video:
            await status.edit("❌ Download failed")
            await log(f"❌ Failed download\n{url}")
            return

        await status.edit("🎞 Processing...")
        fixed, thumb = fix_video(video)

        await app.send_video(
            "me",  # SAVED MESSAGES
            fixed,
            supports_streaming=True,
            thumb=thumb,
            progress=upload_progress,
            progress_args=(status,)
        )

        await status.edit("✅ Sent to Saved Messages")
        await log(f"✅ Uploaded successfully\n{url}")

    except Exception as e:
        await status.edit("❌ Error occurred")
        await log(f"🔥 ERROR\n{e}")

    finally:
        # CLEAN TMP ALWAYS
        for f in os.listdir(TMP_DIR):
            try:
                os.remove(os.path.join(TMP_DIR, f))
            except:
                pass

# ================= START =================

print("Userbot running")
app.run()
