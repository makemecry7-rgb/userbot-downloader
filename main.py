import os
import re
import asyncio
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
SESSION = os.environ.get("SESSION", "user")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Client(SESSION, api_id=API_ID, api_hash=API_HASH)

URL_RE = re.compile(r"https?://\S+")


# ---------- UTILS ----------

def get_codecs(path):
    v = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=nw=1:nk=1",
        path
    ]).decode().strip()

    a = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=nw=1:nk=1",
        path
    ]).decode().strip()

    return v, a


def generate_thumb(video):
    thumb = video.rsplit(".", 1)[0] + ".jpg"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video,
            "-ss", "00:00:01",
            "-vframes", "1",
            "-vf", "scale=320:-1",
            thumb
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return thumb if os.path.exists(thumb) else None


def process_video(src):
    base = src.rsplit(".", 1)[0]
    remuxed = base + "_remux.mp4"

    # 1️⃣ SAFE REMUX
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-map", "0",
            "-c", "copy",
            "-movflags", "+faststart",
            remuxed
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if os.path.exists(remuxed) and os.path.getsize(remuxed) > 5 * 1024 * 1024:
        try:
            v, a = get_codecs(remuxed)
            if v == "h264" and a == "aac":
                os.remove(src)
                return remuxed
        except Exception:
            pass

    # 2️⃣ FORCE RE-ENCODE (ONLY IF REQUIRED)
    encoded = base + "_encoded.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", src,
            "-map", "0",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-profile:v", "main",
            "-level", "4.0",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            encoded
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    if not os.path.exists(encoded) or os.path.getsize(encoded) < 5 * 1024 * 1024:
        raise Exception("FFmpeg failed")

    os.remove(src)
    if os.path.exists(remuxed):
        os.remove(remuxed)

    return encoded


async def yt_download(url):
    out = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-o", out,
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--newline",
        url
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()

    files = sorted(
        [os.path.join(DOWNLOAD_DIR, f) for f in os.listdir(DOWNLOAD_DIR)],
        key=os.path.getmtime,
        reverse=True
    )
    return files[0] if files else None


# ---------- HANDLER ----------

@app.on_message(filters.text)
async def handler(_, msg: Message):
    urls = URL_RE.findall(msg.text)
    if not urls:
        return

    url = urls[0]
    status = await msg.reply("⬇️ Downloading...")

    try:
        file = await yt_download(url)
        if not file:
            await status.edit("❌ Download failed")
            return

        file = process_video(file)
        thumb = generate_thumb(file)

        await status.edit("⬆️ Uploading...")

        await app.send_video(
            "me",
            video=file,
            thumb=thumb,
            supports_streaming=True,
            caption=os.path.basename(file)
        )

        await status.delete()

        if thumb and os.path.exists(thumb):
            os.remove(thumb)
        os.remove(file)

    except Exception as e:
        await status.edit(f"❌ Error:\n{e}")


# ---------- RUN ----------

app.run()
