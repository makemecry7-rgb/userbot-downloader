import os
import re
import time
import requests
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

app = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)


def human(size):
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}TB"


def download_with_progress(url, path, msg):
    r = requests.get(url, stream=True)
    total = int(r.headers.get("content-length", 0))
    done = 0
    last = time.time()

    with open(path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)

                if time.time() - last > 2:
                    percent = (done / total) * 100 if total else 0
                    msg.edit_text(
                        f"📥 Downloading\n{percent:.1f}% | {human(done)}/{human(total)}"
                    )
                    last = time.time()


def convert_to_mp4(src):
    dst = src.rsplit(".", 1)[0] + ".mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-c:v", "copy", "-c:a", "copy", dst],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return dst


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
            files.append(
                {
                    "name": info["name"],
                    "url": f"https://pixeldrain.com/api/file/{fid}",
                }
            )

        else:
            cid = gf.group(1)
            data = requests.get(
                f"https://api.gofile.io/getContent?contentId={cid}"
            ).json()
            for f in data["data"]["contents"].values():
                if f["type"] == "file":
                    files.append(
                        {
                            "name": f["name"],
                            "url": f["link"],
                        }
                    )

        for item in files:
            filename = item["name"]
            filepath = os.path.join(DOWNLOAD_DIR, filename)

            await status.edit(f"📥 Downloading\n{filename}")
            download_with_progress(item["url"], filepath, status)

            ext = filename.lower().split(".")[-1]

            if ext != "mp4":
                await status.edit(f"🎬 Converting to MP4\n{filename}")
                new_path = convert_to_mp4(filepath)
                os.remove(filepath)
                filepath = new_path

            await status.edit(f"📤 Uploading\n{os.path.basename(filepath)}")

            await message.reply_video(
                video=filepath,
                supports_streaming=True,
                caption=os.path.basename(filepath),
                progress=lambda c, t: status.edit_text(
                    f"📤 Uploading\n{(c/t)*100:.1f}% | {human(c)}/{human(t)}"
                ),
            )

            os.remove(filepath)

        await status.edit("✅ Done")

    except Exception as e:
        await status.edit(f"❌ Error:\n`{e}`")


app.run()
