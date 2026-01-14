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

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
BUNKR_RE = re.compile(r"https?://(www\.)?bunkr\.(cr|pk|fi|ru)/")

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
    for base, _, names in os.walk(root):
        for n in names:
            p = os.path.join(base, n)
            if p.lower().endswith(ALLOWED_EXT):
                files.append(p)
    return files

# ---------- PIXELDRAIN ----------
def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

# ---------- MEGA (mega-cmd primary, megatools fallback) ----------
def download_mega(url):
    if not ("mega.nz/file/" in url or "mega.nz/folder/" in url):
        raise Exception("Invalid MEGA link (send file or folder link)")

    # ---- PRIMARY: mega-cmd ----
    try:
        subprocess.run(
            ["mega-cmd-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )

        subprocess.run(
            ["mega-login"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False
        )

        subprocess.run(
            ["mega-get", url, DOWNLOAD_DIR],
            check=True
        )
        return

    except Exception:
        pass  # fallback below

    # ---- FALLBACK: megatools (megadl) ----
    subprocess.run(
        ["megadl", "--path", DOWNLOAD_DIR, url],
        check=True
    )

# ---------- M3U8 DETECTION ----------
def extract_m3u8(url):
    try:
        p = subprocess.run(
            [
                "yt-dlp",
                "--cookies", COOKIES_FILE,
                "--dump-json",
                "--no-playlist",
                url
            ],
            capture_output=True,
            text=True,
            check=True
        )
        for line in p.stdout.splitlines():
            if ".m3u8" in line:
                return line.strip()
    except Exception:
        return None
    return None

# ---------- YT-DLP WITH FALLBACK ----------
def download_ytdlp(url, out):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    base_cmd = [
        "yt-dlp",
        "-f", "bv*+ba/best",
        "--cookies", COOKIES_FILE,
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "--referer", referer,
        "--add-header", f"Origin:{referer}",
        "--allow-unplayable-formats",
        "--merge-output-format", "mkv",
        "--remux-video", "mp4",
        "--no-playlist",
        "-o", out,
        url
    ]

    try:
        subprocess.run(base_cmd, check=True)
        return
    except subprocess.CalledProcessError:
        pass

    m3u8 = extract_m3u8(url)
    if not m3u8:
        raise Exception("yt-dlp failed and no m3u8 found")

    subprocess.run(
        [
            "yt-dlp",
            "--cookies", COOKIES_FILE,
            "--user-agent", "Mozilla/5.0",
            "--referer", referer,
            "--add-header", f"Origin:{referer}",
            "-o", out,
            m3u8
        ],
        check=True
    )

# ---------- FIX STREAMING ----------
def faststart_and_thumb(src):
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    thumb = src.rsplit(".", 1)[0] + ".jpg"

    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    subprocess.run(
        ["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    os.remove(src)
    return fixed, thumb

# ---------- SPLIT ----------
def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)

    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as o:
                o.write(f.read(SPLIT_SIZE))
            parts.append(part)

    os.remove(path)
    return parts

# ================= USERBOT =================

@app.on_message(filters.private & filters.text)
async def handler(_, m: Message):
    url = m.text.strip()
    status = await m.reply("🔍 Processing link...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if BUNKR_RE.search(url):
            await status.edit("❌ Bunkr is blocked on Railway")
            return

        if (px := PIXELDRAIN_RE.search(url)):
            fid = px.group(1)
            info = requests.get(
                f"https://pixeldrain.com/api/file/{fid}/info"
            ).json()
            path = os.path.join(DOWNLOAD_DIR, info["name"])
            await status.edit("⬇️ Downloading from Pixeldrain...")
            download_pixeldrain(fid, path)

        elif MEGA_RE.search(url):
            await status.edit("⬇️ Downloading from MEGA...")
            download_mega(url)

        else:
            await status.edit("🎥 Extracting video (m3u8 fallback enabled)...")
            out = os.path.join(DOWNLOAD_DIR, "%(title).80s.%(ext)s")
            download_ytdlp(url, out)

        files = collect_files(DOWNLOAD_DIR)
        if not files:
            raise Exception("No videos found")

        await status.edit(f"📦 Uploading {len(files)} file(s)...")

        for f in files:
            fixed, thumb = faststart_and_thumb(f)

            parts = (
                [fixed]
                if os.path.getsize(fixed) < SPLIT_SIZE
                else split_file(fixed)
            )

            for p in parts:
                await app.send_video(
                    "me",
                    video=p,
                    thumb=thumb,
                    supports_streaming=True,
                    caption=os.path.basename(p),
                )
                os.remove(p)

            if os.path.exists(thumb):
                os.remove(thumb)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")

    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app.run()
