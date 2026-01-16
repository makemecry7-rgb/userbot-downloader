import os
import re
import asyncio
import shutil
import subprocess
import threading
from pyrogram import Client, filters
from pyrogram.types import Message
from http.server import HTTPServer, BaseHTTPRequestHandler

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

# YOUR CHANNEL ID (logs / trash)
LOG_CHANNEL = -1003609000029  # <-- change if needed

DOWNLOAD_DIR = "/tmp/downloads"
UA = "Mozilla/5.0"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")

# ================= WEB SERVER (KOYEB NEEDS THIS) =================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_web():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()

threading.Thread(target=start_web, daemon=True).start()

# ================= PYROGRAM =================

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    in_memory=True
)

# ================= PROGRESS =================

async def progress(current, total, msg, text):
    if not total:
        return
    percent = current * 100 / total
    bar = f"[{'█'*int(percent//10)}{'░'*(10-int(percent//10))}] {percent:.1f}%"
    try:
        await msg.edit(f"{text}\n{bar}")
    except:
        pass

# ================= HELPERS =================

def extract_url(text):
    m = re.search(r"(https?://[^\s]+)", text)
    return m.group(1) if m else None

# ================= DOWNLOAD =================

async def download(url, status):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--user-agent", UA,
        "-o", out,
        url
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    for line in proc.stdout:
        if "%" in line:
            try:
                pct = float(line.split("%")[0].split()[-1])
                bar = f"[{'█'*int(pct//10)}{'░'*(10-int(pct//10))}] {pct:.1f}%"
                await status.edit(f"⬇️ Downloading\n{bar}")
            except:
                pass

    proc.wait()

# ================= HANDLER =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = extract_url(m.text)
    if not url:
        return

    status = await m.reply("⏬ Starting download...")

    try:
        await download(url, status)

        await status.edit("📤 Uploading...")

        for f in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, f)

            await app.send_video(
                "me",  # Saved Messages
                path,
                supports_streaming=True,
                progress=progress,
                progress_args=(status, "⬆️ Uploading")
            )

            # Log copy
            await app.send_document(LOG_CHANNEL, path)

            os.remove(path)

    except Exception as e:
        await app.send_message(LOG_CHANNEL, f"❌ ERROR:\n{e}")

    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    await status.edit("✅ Done")

# ================= START =================

app.run()
