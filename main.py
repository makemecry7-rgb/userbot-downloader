import os
import re
import math
import shutil
import subprocess
import requests
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
SPLIT_SIZE = 1900 * 1024 * 1024  # 1.9GB

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

# ================= HELPERS =================

def is_direct_video(url):
    return url.lower().split("?")[0].endswith(
        (".mp4", ".mkv", ".webm", ".avi", ".mov")
    )

def is_hls(url):
    return ".m3u8" in url.lower()

def download_direct(url, path):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": url
    }
    r = requests.get(url, headers=headers, stream=True, timeout=30)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)

def download_pixeldrain(fid, path):
    r = requests.get(f"https://pixeldrain.com/api/file/{fid}", stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            if c:
                f.write(c)

def download_ytdlp(url, out):
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "--add-header", "Referer:https://bunkr.cr/",
        "--hls-use-mpegts",
        "--allow-unplayable-formats",
        "--merge-output-format", "mp4",
        "-o", out,
        url
    ]
    subpro
