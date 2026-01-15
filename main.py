import os, re, math, shutil, subprocess, requests, time
from pyrogram import Client, filters
from pyrogram.types import Message

# ================= CONFIG =================
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")

DOWNLOAD_DIR = "downloads"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
GOFILE_RE = re.compile(r"gofile\.io/d/([A-Za-z0-9]+)")

# ================= PROGRESS BAR LOGIC =================

def get_pb(current, total):
    """Generates a visual progress bar string."""
    percentage = (current / total) * 100 if total > 0 else 0
    completed = int(percentage / 10)
    return f"[{'█' * completed}{'░' * (10 - completed)}] {percentage:.1f}%"

async def progress_bar(current, total, message, tag):
    """Universal progress callback for Pyrogram and Requests."""
    now = time.time()
    # Throttling updates to every 4 seconds to prevent Telegram flood blocks
    if not hasattr(progress_bar, "last"): progress_bar.last = 0
    if now - progress_bar.last < 4: return 
    progress_bar.last = now
    
    bar = get_pb(current, total)
    status_text = f"**{tag}**\n{bar}\n`{current/1024/1024:.1f} / {total/1024/1024:.1f} MB`"
    try:
        await message.edit(status_text)
    except: pass

async def download_with_pb(url, path, message, tag):
    """Downloads a file while updating a Telegram progress bar."""
    headers = {"User-Agent": UA, "Authorization": f"Bearer {GOFILE_API_TOKEN}"}
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        current = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                f.write(chunk)
                current += len(chunk)
                await progress_bar(current, total, message, tag)

# ================= CORE PROCESSING =================

def fix_video(src):
    """Applies faststart for streaming and deletes the original file."""
    fixed = src.rsplit(".", 1)[0] + "_fixed.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed], capture_output=True)
    if os.path.exists(src): os.remove(src)
    return fixed

# ================= BOT HANDLER =================

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

@app.on_message(filters.private & filters.text)
async def handler(client, m: Message):
    match = re.search(r'(https?://[^\s]+)', m.text)
    if not match: return
    url = match.group(1)
    status = await m.reply("📂 **Analyzing Link...**")

    try:
        queue = []
        if (gf := GOFILE_RE.search(url)):
            res = requests.get(f"api.gofile.io{gf.group(1)}", 
                               headers={"Authorization": f"Bearer {GOFILE_API_TOKEN}"}).json()
            contents = res["data"].get("children", res["data"].get("contents", {}))
            queue = [{"name": item["name"], "link": item["directLink"]} for item in contents.values() if item["type"] == "file"]
        else:
            queue = [{"name": "video.mp4", "link": url}]

        for i, item in enumerate(queue, 1):
            tag = f"Video ({i}/{len(queue)})"
            file_path = os.path.join(DOWNLOAD_DIR, item["name"])
            
            # 1. Download with Bar
            await download_with_pb(item["link"], file_path, status, f"Downloading {tag}")
            
            # 2. Process (Faststart)
            await status.edit(f"⚙️ **Processing {tag}...**")
            fixed_file = fix_video(file_path)
            
            # 3. Upload with Bar
            await status.edit(f"⬆️ **Uploading {tag}...**")
            await client.send_video(
                chat_id=m.chat.id,
                video=fixed_file,
                caption=f"✅ {tag}\n`{item['name']}`",
                supports_streaming=True,
                progress=progress_bar,
                progress_args=(status, f"Uploading {tag}")
            )
            
            # 4. Immediate Cleanup (Railway Space Optimization)
            if os.path.exists(fixed_file): os.remove(fixed_file)

        await status.edit(f"✅ **Done!** {len(queue)} videos sent.")

    except Exception as e:
        await status.edit(f"❌ **Error:**\n`{str(e)}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

if __name__ == "__main__":
    app.run()
