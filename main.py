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
SPLIT_SIZE = 1900 * 1024 * 1024  # Standard TG limit
COOKIES_FILE = "cookies.txt"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
ALLOWED_EXT = (".mp4", ".mkv", ".webm", ".avi", ".mov")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Regex Patterns
PIXELDRAIN_RE = re.compile(r"https?://pixeldrain\.com/u/([A-Za-z0-9]+)")
MEGA_RE = re.compile(r"https?://mega\.nz/")
GOFILE_RE = re.compile(r"https?://gofile\.io/d/([A-Za-z0-9]+)")

# ================= PROGRESS HELPERS =================
def get_pb(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    done = int(percentage / 10)
    return f"[{'█' * done}{'░' * (10 - done)}] {percentage:.1f}%"

async def progress_func(current, total, message, tag):
    now = time.time()
    if not hasattr(progress_func, "last"): progress_func.last = 0
    if now - progress_func.last < 4: return 
    progress_func.last = now
    bar = get_pb(current, total)
    try:
        await message.edit(f"**{tag}**\n{bar}\n`{current/1024/1024:.2f} / {total/1024/1024:.2f} MB`")
    except: pass

# ================= CLIENT =================
app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# ================= HELPERS =================
def extract_clean_url(text):
    match = re.search(r'(https?://[^\s\n]+)', text)
    return match.group(1) if match else None

def collect_files(root):
    files = []
    for base, _, names in os.walk(root):
        for n in names:
            p = os.path.join(base, n)
            if any(p.lower().endswith(ext) for ext in ALLOWED_EXT):
                files.append(p)
    return files

# ---------- GOFILE SOLVER (URL & AUTH FIXED) ----------
async def download_gofile(content_id, status_msg):
    # FIXED: Scheme added and 2026 API path corrected
    headers = {"Authorization": f"Bearer {GOFILE_API_TOKEN}", "User-Agent": UA}
    api_url = f"api.gofile.io{content_id}"
    
    res = requests.get(api_url, headers=headers)
    if res.status_code != 200:
        raise Exception(f"GoFile API Error {res.status_code}. Token might be invalid.")
    
    data = res.json()
    # 2026 Response handling
    contents = data.get("data", {}).get("contents", data.get("data", {}).get("children", {}))
    
    video_items = [item for item in contents.values() if item.get("type") == "file"]
    if not video_items: raise Exception("No videos found in this GoFile link.")
    
    for i, item in enumerate(video_items, 1):
        tag = f"Downloading Video {i}/{len(video_items)}"
        out_path = os.path.join(DOWNLOAD_DIR, item["name"])
        
        # Requests stream download using Bearer Token
        with requests.get(item["directLink"], headers=headers, stream=True) as r:
            r.raise_for_status()
            file_total = int(r.headers.get('content-length', 0))
            current = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        current += len(chunk)
                        await progress_func(current, file_total, status_msg, tag)

# ---------- YT-DLP CORE ----------
def download_ytdlp(url, out_pattern):
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    cmd = [
        "yt-dlp", "--no-playlist", "--user-agent", UA,
        "--add-header", f"Referer:{referer}", "--merge-output-format", "mp4",
        "-o", out_pattern, url
    ]
    if os.path.exists(COOKIES_FILE):
        cmd.extend(["--cookies", COOKIES_FILE])
    subprocess.run(cmd, check=True)

# ---------- VIDEO PROCESSING ----------
def faststart_and_thumb(src):
    base_name = os.path.splitext(src)[0]
    fixed = f"{base_name}_fixed.mp4"
    thumb = f"{base_name}.jpg"
    subprocess.run(["ffmpeg", "-y", "-i", src, "-movflags", "+faststart", "-c", "copy", fixed], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-i", fixed, "-ss", "00:00:01", "-vframes", "1", thumb], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(src): os.remove(src)
    return fixed, (thumb if os.path.exists(thumb) else None)

def split_file(path):
    parts = []
    size = os.path.getsize(path)
    count = math.ceil(size / SPLIT_SIZE)
    with open(path, "rb") as f:
        for i in range(count):
            part = f"{path}.part{i+1}.mp4"
            with open(part, "wb") as o: o.write(f.read(SPLIT_SIZE))
            parts.append(part)
    if os.path.exists(path): os.remove(path)
    return parts

# ================= USERBOT HANDLER =================
@app.on_message(filters.me & filters.private & filters.text)
async def handler(client, m: Message):
    if m.chat.id != client.me.id: return
    
    url = extract_clean_url(m.text)
    if not url: return
    status = await m.reply("⏳ Starting GoFile Downloader...")

    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        if (gf := GOFILE_RE.search(url)):
            await status.edit("📁 GoFile folder detected. Authenticating...")
            await download_gofile(gf.group(1), status)
        elif (px := PIXELDRAIN_RE.search(url)):
            await status.edit("💧 Pixeldrain detected...")
            download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))
        else:
            await status.edit("🎥 Extracting video...")
            download_ytdlp(url, os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"))

        files = collect_files(DOWNLOAD_DIR)
        if not files: raise Exception("No media found.")

        for i, f in enumerate(files, 1):
            tag = f"Uploading {i}/{len(files)}"
            fixed, thumb = faststart_and_thumb(f)
            parts = [fixed] if os.path.getsize(fixed) < SPLIT_SIZE else split_file(fixed)
            for p in parts:
                await client.send_video(
                    chat_id="me", 
                    video=p, 
                    thumb=thumb, 
                    supports_streaming=True, 
                    caption=f"`{os.path.basename(p)}`",
                    progress=progress_func,
                    progress_args=(status, tag)
                )
                if os.path.exists(p): os.remove(p)
            if thumb and os.path.exists(thumb): os.remove(thumb)

        await status.edit("✅ Success! All videos saved to Saved Messages.")
    except Exception as e:
        await status.edit(f"❌ Error:\n`{str(e)}`")
    finally:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)

if __name__ == "__main__":
    app.run()
