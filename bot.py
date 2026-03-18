"""
═══════════════════════════════════════════════════════════════
 KENSHIN VIDEO CONVERTER BOT — bot.py (single file)
 Framework: Pyrogram (handles 2GB+ files)
 Output: HLS stream link (.m3u8) — directly plays on website
 Deploy: Railway → set env variables:
   BOT_TOKEN, API_ID, API_HASH, BASE_URL
═══════════════════════════════════════════════════════════════
"""

import os, sys, asyncio, subprocess, shutil, uuid, json, time, math
import logging
from pathlib import Path
from aiohttp import web
import aiofiles

from pyrogram import Client, filters
from pyrogram.types import Message

# ── Logging ──
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("KenshinBot")

# ── Config from env ──
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID    = int(os.environ.get("API_ID", "0"))
API_HASH  = os.environ.get("API_HASH", "")
BASE_URL  = os.environ.get("BASE_URL", "").rstrip("/")   # e.g. https://kenshin-bot.up.railway.app
PORT      = int(os.environ.get("PORT", "8080"))

if not all([BOT_TOKEN, API_ID, API_HASH, BASE_URL]):
    log.error("❌ Missing env vars! Need: BOT_TOKEN, API_ID, API_HASH, BASE_URL")
    sys.exit(1)

# ── Temp dir ──
TMP = Path("/tmp/kenshin")
TMP.mkdir(parents=True, exist_ok=True)

# ── HLS jobs store: job_id → {status, out_dir, segments, error} ──
JOBS: dict = {}

# ══════════════════════════════════════════════════════════════
# FFMPEG HELPERS
# ══════════════════════════════════════════════════════════════

def fmt_time(seconds: float) -> str:
    if not seconds or math.isnan(seconds): return "0:00"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

async def get_info(path_or_url: str) -> dict | None:
    """Get video info via ffprobe"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", path_or_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        data    = json.loads(stdout)
        streams = data.get("streams", [])
        video   = next((s for s in streams if s["codec_type"] == "video"), None)
        audio   = next((s for s in streams if s["codec_type"] == "audio"), None)
        h       = video.get("height", 0) if video else 0
        label   = ("8K" if h>=4320 else "4K" if h>=2160 else "2K" if h>=1440
                   else "1080p" if h>=1080 else "720p" if h>=720
                   else "480p" if h>=480 else "360p" if h>=360 else f"{h}p")
        vc = (video.get("codec_name","unknown") if video else "unknown").lower()
        ac = (audio.get("codec_name","unknown") if audio else "unknown").lower()
        return {
            "video_codec": vc,
            "audio_codec": ac,
            "width":  video.get("width",0)  if video else 0,
            "height": h,
            "label":  label,
            "duration": float(data.get("format",{}).get("duration",0) or 0),
            "size":     int(data.get("format",{}).get("size",0) or 0),
            "needs_convert": (
                vc not in ("h264","avc1","vp8","vp9","av1") or
                ac not in ("aac","mp3","opus","vorbis","flac")
            ),
        }
    except Exception as e:
        log.error(f"[INFO] {e}")
        return None

async def convert_to_hls(
    input_path: str,
    job_id: str,
    progress_cb=None,
) -> Path:
    """Convert any video to HLS (.m3u8 + .ts segments)"""
    out_dir = TMP / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    m3u8    = out_dir / "index.m3u8"

    JOBS[job_id] = {"status": "processing", "out_dir": str(out_dir),
                    "segments": 0, "started": time.time(), "error": None}

    cmd = [
        "ffmpeg", "-y", "-loglevel", "info",
        "-i", input_path,
        # Video → H.264 original quality
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-profile:v", "high", "-level:v", "4.2",
        "-pix_fmt", "yuv420p",
        "-g", "48", "-sc_threshold", "0",
        # Audio → AAC stereo (fixes AC3/DTS/5.1/TrueHD)
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000",
        # HLS output
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
        "-hls_segment_type", "mpegts",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(out_dir / "seg%04d.ts"),
        str(m3u8),
    ]

    log.info(f"[HLS] Job {job_id}: {input_path}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    dur_sec   = 0.0
    last_pct  = -1
    last_cb   = time.time()

    # Parse FFmpeg stderr for progress
    while True:
        line_b = await proc.stderr.readline()
        if not line_b:
            break
        line = line_b.decode(errors="ignore")

        # Parse duration
        if not dur_sec and "Duration:" in line:
            try:
                t = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = t.split(":")
                dur_sec = int(h)*3600 + int(m)*60 + float(s)
            except: pass

        # Parse progress time
        if "time=" in line:
            try:
                t = line.split("time=")[1].split(" ")[0].strip()
                h, m, s = t.split(":")
                cur = int(h)*3600 + int(m)*60 + float(s)
                if dur_sec > 0:
                    pct = min(99, int(cur / dur_sec * 100))
                    # Count segments
                    segs = len(list(out_dir.glob("*.ts")))
                    JOBS[job_id]["segments"] = segs
                    now = time.time()
                    if pct != last_pct and (now - last_cb) >= 5 and progress_cb:
                        last_pct = pct
                        last_cb  = now
                        await progress_cb(pct, cur, dur_sec, segs)
            except: pass

    await proc.wait()

    if proc.returncode != 0:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"]  = f"FFmpeg exit code {proc.returncode}"
        raise RuntimeError(f"FFmpeg failed (code {proc.returncode})")

    JOBS[job_id]["status"]   = "done"
    JOBS[job_id]["segments"] = len(list(out_dir.glob("*.ts")))
    log.info(f"[HLS] Job {job_id} done — {JOBS[job_id]['segments']} segments")
    return m3u8

def cleanup_job(job_id: str, delay: int = 7200):
    """Schedule cleanup after delay seconds (default 2h)"""
    async def _clean():
        await asyncio.sleep(delay)
        job = JOBS.pop(job_id, None)
        if job:
            try: shutil.rmtree(job["out_dir"], ignore_errors=True)
            except: pass
        log.info(f"[CLEAN] Job {job_id} cleaned up")
    asyncio.create_task(_clean())

# ══════════════════════════════════════════════════════════════
# HTTP SERVER — serves HLS segments
# ══════════════════════════════════════════════════════════════

async def handle_hls(request: web.Request) -> web.Response:
    job_id   = request.match_info["job_id"]
    filename = request.match_info["filename"]

    job = JOBS.get(job_id)
    if not job:
        return web.Response(status=404, text="Job not found or expired")

    file_path = Path(job["out_dir"]) / Path(filename).name  # prevent traversal

    if not file_path.exists():
        return web.Response(status=404, text="Segment not ready")

    mime = ("application/vnd.apple.mpegurl"
            if file_path.suffix == ".m3u8" else "video/mp2t")

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache",
        "Content-Type": mime,
    }

    async with aiofiles.open(file_path, "rb") as f:
        data = await f.read()

    return web.Response(body=data, headers=headers)

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "service": "🎌 Kenshin Converter Bot",
        "status":  "running ✅",
        "jobs":    len(JOBS),
    })

async def start_http_server():
    app = web.Application()
    app.router.add_get("/",                          handle_health)
    app.router.add_get("/hls/{job_id}/{filename}",   handle_hls)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info(f"✅ HTTP server on port {PORT}")

# ══════════════════════════════════════════════════════════════
# PYROGRAM BOT
# ══════════════════════════════════════════════════════════════

app = Client(
    "kenshin_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)

# ── /start ──
@app.on_message(filters.command("start"))
async def cmd_start(_, msg: Message):
    await msg.reply_text(
        "🎌 **Kenshin Video Converter Bot**\n\n"
        "Mujhe bhejo:\n"
        "• 🎬 **Video file** — direct upload (2GB tak!)\n"
        "• 📄 **MKV/AVI document** — file attach karo\n"
        "• 🔗 **Video URL** — catbox, direct MP4/MKV link\n"
        "• 📺 **HLS link** — `.m3u8` streaming URL\n\n"
        "Main convert karunga:\n"
        "H.265 → H.264 ✅\n"
        "AC3/DTS/TrueHD → AAC ✅\n"
        "MKV → HLS ✅\n\n"
        "**Return milega:**\n"
        "🔗 HLS link — seedha website pe paste karo!\n\n"
        "/help — details",
        parse_mode="markdown",
    )

# ── /help ──
@app.on_message(filters.command("help"))
async def cmd_help(_, msg: Message):
    await msg.reply_text(
        "📖 **Help**\n\n"
        "**3 tarike se bhejo:**\n\n"
        "1️⃣ **Video upload:**\n"
        "   Telegram mein video/document attach karo\n"
        "   (2GB tak support!)\n\n"
        "2️⃣ **URL bhejo:**\n"
        "   `https://files.catbox.moe/abc.mkv`\n\n"
        "3️⃣ **HLS link bhejo:**\n"
        "   `https://example.com/stream/index.m3u8`\n\n"
        "**Response mein milega:**\n"
        "✅ HLS play URL — website pe directly chalega!\n\n"
        "**Supported input:**\n"
        "MKV, MP4, AVI, WebM, HLS (.m3u8), any direct stream\n\n"
        "**Converted output:**\n"
        "H.264 + AAC HLS — Chrome/Firefox/Safari sab pe ✅",
        parse_mode="markdown",
    )

# ══════════════════════════════════════════════════════════════
# CORE CONVERT HANDLER
# ══════════════════════════════════════════════════════════════

async def process_convert(msg: Message, input_source: str, display_name: str = ""):
    """
    input_source: local file path OR URL/HLS link
    Converts to HLS and replies with play URL.
    """
    job_id  = str(uuid.uuid4().hex[:10])
    is_url  = input_source.startswith("http")

    status = await msg.reply_text("🔍 **Codec check kar raha hoon...**", parse_mode="markdown")

    async def edit(text: str):
        try: await status.edit_text(text, parse_mode="markdown")
        except: pass

    try:
        # ── Get info ──
        info = await get_info(input_source)

        if info:
            vc = info["video_codec"].upper()
            ac = info["audio_codec"].upper()
            info_text = (
                f"📊 **Video Info:**\n"
                f"• Resolution: `{info['label']}` ({info['width']}×{info['height']})\n"
                f"• Video: `{vc}`\n"
                f"• Audio: `{ac}`\n"
                f"• Duration: `{fmt_time(info['duration'])}`\n\n"
            )
        else:
            info_text = f"🔗 **Source:** `{display_name or input_source[:60]}`\n\n"

        # ── Already browser-safe? ──
        if info and not info["needs_convert"]:
            play_url = input_source if is_url else None
            await edit(
                info_text +
                "✅ **Already H.264 + AAC hai!**\n"
                "Koi conversion nahi chahiye.\n\n"
                + (f"🔗 **Direct play URL:**\n`{play_url}`\n\nSeedha website mein use karo!" if play_url else
                   "File already browser-safe hai!")
            )
            return

        # ── Start conversion ──
        await edit(info_text + "⚙️ **Convert ho rahi hai...**\n`[░░░░░░░░░░] 0%`")

        async def progress(pct, cur, dur, segs):
            bar     = "█" * (pct // 10) + "░" * (10 - pct // 10)
            elapsed = time.time() - JOBS[job_id]["started"]
            speed   = cur / elapsed if elapsed > 0 else 0
            eta     = (dur - cur) / speed if speed > 0 else 0
            await edit(
                info_text +
                f"⚙️ **Converting...**\n"
                f"`[{bar}] {pct}%`\n"
                f"⏱ `{fmt_time(cur)} / {fmt_time(dur)}`\n"
                f"📦 Segments ready: `{segs}`\n"
                f"⚡ Speed: `{speed:.1f}x` | ETA: `{fmt_time(eta)}`"
            )

        await convert_to_hls(input_source, job_id, progress)

        # ── Build play URL ──
        play_url = f"{BASE_URL}/hls/{job_id}/index.m3u8"
        segs     = JOBS[job_id]["segments"]

        await edit(
            info_text +
            f"✅ **Convert ho gayi!** 🎌\n\n"
            f"📦 Segments: `{segs}`\n"
            f"⏳ Valid: **2 hours**\n\n"
            f"🔗 **HLS Play URL:**\n"
            f"`{play_url}`\n\n"
            f"👆 Yeh URL apni website ke admin panel mein episode URL mein paste karo!\n"
            f"Chrome/Firefox/Safari sab pe chalegi ✅"
        )

        # Schedule cleanup after 2 hours
        cleanup_job(job_id, delay=7200)

    except Exception as e:
        log.error(f"[CONVERT] {e}")
        await edit(
            f"❌ **Error hua:**\n`{str(e)[:200]}`\n\n"
            "Check karo:\n"
            "• File/URL accessible hai?\n"
            "• Format supported hai?"
        )

    finally:
        # Cleanup downloaded file if local
        if not is_url and Path(input_source).exists():
            try: os.remove(input_source)
            except: pass

# ══════════════════════════════════════════════════════════════
# HANDLERS — Video file
# ══════════════════════════════════════════════════════════════

@app.on_message(filters.video | filters.document)
async def handle_file(client, msg: Message):
    media = msg.video or msg.document
    if not media:
        return

    # For documents, check if it's a video file
    if msg.document:
        fname = (msg.document.file_name or "").lower()
        if not any(fname.endswith(ext) for ext in
                   [".mp4",".mkv",".avi",".webm",".mov",".flv",".m4v",".ts"]):
            await msg.reply_text("⚠️ Sirf video files support hoti hain (MP4, MKV, AVI, WebM...)")
            return

    file_name = getattr(media, "file_name", None) or "video.mp4"
    file_size = getattr(media, "file_size", 0) or 0
    size_mb   = file_size / 1024 / 1024

    status = await msg.reply_text(
        f"📥 **Downloading...**\n"
        f"📄 `{file_name}` ({size_mb:.1f} MB)\n\n"
        f"⏳ Pyrogram se download ho rahi hai...",
        parse_mode="markdown",
    )

    async def edit(text):
        try: await status.edit_text(text, parse_mode="markdown")
        except: pass

    try:
        # ── Download with Pyrogram (handles 2GB) ──
        job_id  = str(uuid.uuid4().hex[:10])
        dl_dir  = TMP / f"dl_{job_id}"
        dl_dir.mkdir(parents=True, exist_ok=True)
        ext     = Path(file_name).suffix or ".mp4"
        dl_path = str(dl_dir / f"input{ext}")

        last_edit  = [0.0]
        start_time = time.time()

        async def dl_progress(current, total):
            now = time.time()
            if now - last_edit[0] < 3: return
            last_edit[0] = now
            pct     = int(current / total * 100) if total else 0
            bar     = "█"*(pct//10) + "░"*(10-pct//10)
            elapsed = now - start_time
            speed   = current / elapsed / 1024 / 1024 if elapsed > 0 else 0
            await edit(
                f"📥 **Downloading...**\n"
                f"📄 `{file_name}`\n"
                f"`[{bar}] {pct}%`\n"
                f"📊 `{current/1024/1024:.1f} / {total/1024/1024:.1f} MB`\n"
                f"⚡ `{speed:.1f} MB/s`"
            )

        await msg.download(file_name=dl_path, progress=dl_progress)
        await edit(f"✅ **Download complete!**\n⚙️ Convert shuru ho rahi hai...")

        # ── Convert ──
        await process_convert(msg, dl_path, file_name)

    except Exception as e:
        log.error(f"[FILE] {e}")
        await edit(f"❌ **Error:** `{str(e)[:200]}`")
    finally:
        # cleanup dl dir
        try: shutil.rmtree(str(dl_dir), ignore_errors=True)
        except: pass

# ══════════════════════════════════════════════════════════════
# HANDLER — URL / HLS text message
# ══════════════════════════════════════════════════════════════

@app.on_message(filters.text & ~filters.command(["start","help"]))
async def handle_url(_, msg: Message):
    text = (msg.text or "").strip()

    # Extract URL
    import re
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        await msg.reply_text(
            "❓ Mujhe bhejo:\n"
            "• Video file (attach karo)\n"
            "• Video URL (catbox, direct link)\n"
            "• HLS link (.m3u8)\n\n"
            "/help se details dekho"
        )
        return

    url = url_match.group(0)
    lo  = url.lower()

    kind = "📺 HLS stream" if ".m3u8" in lo else "🔗 Video URL"
    await msg.reply_text(f"{kind} mili:\n`{url[:80]}`\n\n⏳ Process ho rahi hai...", parse_mode="markdown")

    await process_convert(msg, url, url.split("/")[-1][:40])

# ══════════════════════════════════════════════════════════════
# MAIN — Run bot + HTTP server together
# ══════════════════════════════════════════════════════════════

async def main():
    log.info("🎌 Starting Kenshin Converter Bot...")
    await start_http_server()
    await app.start()
    me = await app.get_me()
    log.info(f"✅ Bot started: @{me.username}")
    log.info(f"✅ HLS server: {BASE_URL}")
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
