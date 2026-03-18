"""
═══════════════════════════════════════════════════════════════
 KENSHIN VIDEO CONVERTER BOT — bot.py (single file)
 Library: python-telegram-bot v20 (async)
 Output: HLS stream link (.m3u8) — directly plays on website
 Deploy: Railway → set env variables:
   BOT_TOKEN, BASE_URL
═══════════════════════════════════════════════════════════════
"""

import os, sys, asyncio, subprocess, shutil, uuid, json, time, math, re, logging
from pathlib import Path
from threading import Thread

import requests
from aiohttp import web
import aiofiles

from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("KenshinBot")

# ── Config ──
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BASE_URL  = os.environ.get("BASE_URL", "").rstrip("/")
PORT      = int(os.environ.get("PORT", "8080"))

if not BOT_TOKEN:
    log.error("❌ BOT_TOKEN env variable not set!")
    sys.exit(1)

if not BASE_URL:
    log.error("❌ BASE_URL env variable not set! e.g. https://yourapp.up.railway.app")
    sys.exit(1)

# ── Temp dir ──
TMP = Path("/tmp/kenshin")
TMP.mkdir(parents=True, exist_ok=True)

# ── HLS jobs: job_id → {status, out_dir, segments, started, error} ──
JOBS: dict = {}

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def fmt_time(seconds) -> str:
    if not seconds or math.isnan(float(seconds)): return "0:00"
    seconds = float(seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def get_info(path_or_url: str) -> dict | None:
    """Get video codec info via ffprobe (sync)"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path_or_url],
            capture_output=True, text=True, timeout=60
        )
        data    = json.loads(result.stdout)
        streams = data.get("streams", [])
        video   = next((s for s in streams if s["codec_type"] == "video"), None)
        audio   = next((s for s in streams if s["codec_type"] == "audio"), None)
        h       = int(video.get("height", 0)) if video else 0
        label   = ("8K" if h>=4320 else "4K" if h>=2160 else "2K" if h>=1440
                   else "1080p" if h>=1080 else "720p" if h>=720
                   else "480p" if h>=480 else "360p" if h>=360 else f"{h}p")
        vc = (video.get("codec_name","unknown") if video else "unknown").lower()
        ac = (audio.get("codec_name","unknown") if audio else "unknown").lower()
        return {
            "video_codec": vc,
            "audio_codec": ac,
            "width":  int(video.get("width",0))  if video else 0,
            "height": h,
            "label":  label,
            "duration": float(data.get("format",{}).get("duration") or 0),
            "needs_convert": (
                vc not in ("h264","avc1","vp8","vp9","av1") or
                ac not in ("aac","mp3","opus","vorbis","flac")
            ),
        }
    except Exception as e:
        log.error(f"[INFO] {e}")
        return None

def download_file(url: str, dest: str, progress_cb=None) -> str:
    """Download URL to dest with progress callback"""
    resp = requests.get(url, stream=True, timeout=60,
                        headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    total   = int(resp.headers.get("content-length", 0))
    done    = 0
    last_cb = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024*1024):
            if chunk:
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if progress_cb and total and now - last_cb >= 3:
                    last_cb = now
                    progress_cb(done, total)
    return dest

# ══════════════════════════════════════════════════════════════
# FFMPEG CONVERT → HLS (runs in thread)
# ══════════════════════════════════════════════════════════════

def convert_to_hls_sync(input_path: str, job_id: str, progress_cb=None):
    """Convert video to HLS — runs synchronously in thread pool"""
    out_dir = TMP / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    m3u8    = out_dir / "index.m3u8"

    JOBS[job_id] = {
        "status":   "processing",
        "out_dir":  str(out_dir),
        "segments": 0,
        "started":  time.time(),
        "error":    None,
    }

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
        # HLS
        "-f", "hls",
        "-hls_time", "4",
        "-hls_list_size", "0",
        "-hls_segment_type", "mpegts",
        "-hls_flags", "independent_segments",
        "-hls_segment_filename", str(out_dir / "seg%04d.ts"),
        str(m3u8),
    ]

    log.info(f"[HLS] Job {job_id}: {input_path}")

    proc = subprocess.Popen(
        cmd, stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        universal_newlines=True
    )

    dur_sec  = 0.0
    last_pct = -1
    last_cb  = 0.0

    for line in proc.stderr:
        # Parse duration
        if not dur_sec and "Duration:" in line:
            try:
                t = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = t.split(":")
                dur_sec = int(h)*3600 + int(m)*60 + float(s)
            except: pass

        # Parse progress
        if "time=" in line:
            try:
                t = line.split("time=")[1].split(" ")[0].strip()
                h, m, s = t.split(":")
                cur = int(h)*3600 + int(m)*60 + float(s)
                if dur_sec > 0:
                    pct  = min(99, int(cur / dur_sec * 100))
                    segs = len(list(out_dir.glob("*.ts")))
                    JOBS[job_id]["segments"] = segs
                    now = time.time()
                    if pct != last_pct and now - last_cb >= 5 and progress_cb:
                        last_pct = pct
                        last_cb  = now
                        progress_cb(pct, cur, dur_sec, segs)
            except: pass

    proc.wait()

    if proc.returncode != 0:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"]  = f"FFmpeg exit code {proc.returncode}"
        raise RuntimeError(f"FFmpeg failed (code {proc.returncode})")

    segs = len(list(out_dir.glob("*.ts")))
    JOBS[job_id]["status"]   = "done"
    JOBS[job_id]["segments"] = segs
    log.info(f"[HLS] Job {job_id} done — {segs} segments")
    return str(m3u8)

async def convert_to_hls(input_path: str, job_id: str, progress_cb=None):
    """Async wrapper — runs sync convert in thread pool"""
    loop = asyncio.get_event_loop()

    # Wrap sync progress_cb to schedule coroutine from thread
    def sync_progress(pct, cur, dur, segs):
        if progress_cb:
            asyncio.run_coroutine_threadsafe(
                progress_cb(pct, cur, dur, segs), loop
            )

    await loop.run_in_executor(
        None, convert_to_hls_sync, input_path, job_id, sync_progress
    )

def schedule_cleanup(job_id: str, delay: int = 7200):
    """Delete HLS files after delay seconds"""
    async def _clean():
        await asyncio.sleep(delay)
        job = JOBS.pop(job_id, None)
        if job:
            shutil.rmtree(job["out_dir"], ignore_errors=True)
            log.info(f"[CLEAN] Job {job_id} cleaned")
    asyncio.create_task(_clean())

# ══════════════════════════════════════════════════════════════
# HTTP SERVER — serves HLS segments with CORS
# ══════════════════════════════════════════════════════════════

async def handle_hls(request: web.Request) -> web.Response:
    job_id   = request.match_info["job_id"]
    filename = request.match_info["filename"]
    job      = JOBS.get(job_id)

    if not job:
        return web.Response(status=404, text="Job not found or expired")

    file_path = Path(job["out_dir"]) / Path(filename).name

    if not file_path.exists():
        return web.Response(status=404, text="Segment not ready yet")

    mime = ("application/vnd.apple.mpegurl"
            if file_path.suffix == ".m3u8" else "video/mp2t")

    async with aiofiles.open(file_path, "rb") as f:
        data = await f.read()

    return web.Response(body=data, headers={
        "Content-Type":                mime,
        "Access-Control-Allow-Origin": "*",
        "Cache-Control":               "no-cache",
    })

async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({
        "service": "Kenshin Converter Bot",
        "status":  "running",
        "jobs":    len(JOBS),
    })

async def start_http():
    http_app = web.Application()
    http_app.router.add_get("/",                        handle_health)
    http_app.router.add_get("/hls/{job_id}/{filename}", handle_hls)
    runner = web.AppRunner(http_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info(f"✅ HTTP server on :{PORT}")

# ══════════════════════════════════════════════════════════════
# CORE CONVERT HANDLER
# ══════════════════════════════════════════════════════════════

async def process_convert(update: Update, input_source: str, display_name: str = ""):
    is_url   = input_source.startswith("http")
    job_id   = uuid.uuid4().hex[:10]

    status_msg = await update.message.reply_text(
        "🔍 *Codec check kar raha hoon...*",
        parse_mode="Markdown"
    )

    async def edit(text: str):
        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            log.warning(f"[EDIT] {e}")

    try:
        # ── Get info ──
        info = await asyncio.get_event_loop().run_in_executor(
            None, get_info, input_source
        )

        if info:
            vc = info["video_codec"].upper()
            ac = info["audio_codec"].upper()
            info_text = (
                f"📊 *Video Info:*\n"
                f"• Resolution: `{info['label']}` ({info['width']}×{info['height']})\n"
                f"• Video: `{vc}`\n"
                f"• Audio: `{ac}`\n"
                f"• Duration: `{fmt_time(info['duration'])}`\n\n"
            )
        else:
            info_text = f"🔗 *Source:* `{(display_name or input_source)[:60]}`\n\n"

        # ── Already browser safe? ──
        if info and not info["needs_convert"]:
            msg = info_text + "✅ *Already H.264 + AAC hai!*\nConversion ki zarurat nahi.\n\n"
            if is_url:
                msg += f"🔗 *Direct play URL:*\n`{input_source}`\n\nSeedha website mein use karo\\!"
            await edit(msg)
            return

        # ── Start convert ──
        await edit(info_text + "⚙️ *Convert ho rahi hai...*\n`[░░░░░░░░░░] 0%`")

        async def on_progress(pct, cur, dur, segs):
            bar     = "█"*(pct//10) + "░"*(10 - pct//10)
            elapsed = time.time() - JOBS[job_id]["started"]
            speed   = (cur / elapsed) if elapsed > 0 else 0
            eta     = ((dur - cur) / speed) if speed > 0 else 0
            await edit(
                info_text +
                f"⚙️ *Converting...*\n"
                f"`[{bar}] {pct}%`\n"
                f"⏱ `{fmt_time(cur)} / {fmt_time(dur)}`\n"
                f"📦 Segments ready: `{segs}`\n"
                f"⚡ Speed: `{speed:.1f}x` | ETA: `{fmt_time(eta)}`"
            )

        await convert_to_hls(input_source, job_id, on_progress)

        play_url = f"{BASE_URL}/hls/{job_id}/index.m3u8"
        segs     = JOBS[job_id]["segments"]

        await edit(
            info_text +
            f"✅ *Convert ho gayi\\!* 🎌\n\n"
            f"📦 Segments: `{segs}`\n"
            f"⏳ Valid: *2 hours*\n\n"
            f"🔗 *HLS Play URL:*\n"
            f"`{play_url}`\n\n"
            f"👆 Yeh URL admin panel mein episode URL mein paste karo\\!\n"
            f"Chrome/Firefox/Safari sab pe chalegi ✅"
        )

        schedule_cleanup(job_id, delay=7200)

    except Exception as e:
        log.error(f"[PROCESS] {e}")
        await edit(
            f"❌ *Error:*\n`{str(e)[:300]}`\n\n"
            "Check karo:\n• URL accessible hai?\n• Format supported hai?"
        )
    finally:
        if not is_url and Path(input_source).exists():
            try: os.remove(input_source)
            except: pass

# ══════════════════════════════════════════════════════════════
# TELEGRAM COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎌 *Kenshin Video Converter Bot*\n\n"
        "Mujhe bhejo:\n"
        "• 🎬 *Video file* — direct upload karo\n"
        "• 📄 *MKV/AVI document* — file attach karo\n"
        "• 🔗 *Video URL* — catbox, direct MP4/MKV link\n"
        "• 📺 *HLS link* — `.m3u8` streaming URL\n\n"
        "Main convert karunga:\n"
        "H\\.265 → H\\.264 ✅\n"
        "AC3/DTS/TrueHD → AAC ✅\n"
        "MKV → HLS ✅\n\n"
        "*Return milega:*\n"
        "🔗 HLS link — website pe paste karo\\!\n\n"
        "/help — details",
        parse_mode="MarkdownV2"
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "*3 tarike se bhejo:*\n\n"
        "1️⃣ *Video upload:*\n"
        "   Video/document attach karo\n\n"
        "2️⃣ *URL bhejo:*\n"
        "`https://files.catbox.moe/abc.mkv`\n\n"
        "3️⃣ *HLS link bhejo:*\n"
        "`https://example.com/stream/index.m3u8`\n\n"
        "*Response mein milega:*\n"
        "✅ HLS play URL — website pe directly chalega\\!\n\n"
        "*Supported input:*\n"
        "MKV, MP4, AVI, WebM, HLS \\(\\.m3u8\\)\n\n"
        "*Output:*\n"
        "H\\.264 \\+ AAC HLS — sab browsers pe ✅",
        parse_mode="MarkdownV2"
    )

# ── Video / Document handler ──
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg   = update.message
    media = msg.video or msg.document

    if not media:
        return

    # Documents — check extension
    if msg.document:
        fname = (msg.document.file_name or "").lower()
        exts  = (".mp4",".mkv",".avi",".webm",".mov",".flv",".m4v",".ts",".wmv")
        if not any(fname.endswith(e) for e in exts):
            await msg.reply_text("⚠️ Sirf video files support hoti hain \\(MP4, MKV, AVI, WebM\\.\\.\\.\\)", parse_mode="MarkdownV2")
            return

    file_name = getattr(media, "file_name", None) or "video.mp4"
    file_size = getattr(media, "file_size", 0) or 0
    size_mb   = file_size / 1024 / 1024

    # Telegram Bot API limit = 20MB download via getFile
    # For bigger files user must send URL instead
    if file_size > 20 * 1024 * 1024:
        await msg.reply_text(
            f"⚠️ *File badi hai \\({size_mb:.0f} MB\\)*\n\n"
            "Telegram Bot API sirf *20MB* tak download kar sakta hai\\.\n\n"
            "📤 *Iska solution:*\n"
            "1\\. File ko catbox\\.moe pe upload karo\n"
            "2\\. Woh URL yahan paste karo\n"
            "Main URL se convert kar dunga\\! ✅",
            parse_mode="MarkdownV2"
        )
        return

    status = await msg.reply_text(
        f"📥 *Downloading...*\n"
        f"📄 `{file_name}` \\({size_mb:.1f} MB\\)",
        parse_mode="MarkdownV2"
    )

    try:
        file_obj = await context.bot.get_file(media.file_id)
        dl_dir   = TMP / f"dl_{uuid.uuid4().hex[:8]}"
        dl_dir.mkdir(parents=True, exist_ok=True)
        ext      = Path(file_name).suffix or ".mp4"
        dl_path  = str(dl_dir / f"input{ext}")

        await file_obj.download_to_drive(dl_path)
        await status.edit_text("✅ *Download complete\\! Converting...*", parse_mode="MarkdownV2")

        await process_convert(update, dl_path, file_name)

    except Exception as e:
        log.error(f"[FILE] {e}")
        await status.edit_text(f"❌ *Error:* `{str(e)[:200]}`", parse_mode="MarkdownV2")
    finally:
        try: shutil.rmtree(str(dl_dir), ignore_errors=True)
        except: pass

# ── URL / HLS text handler ──
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        await update.message.reply_text(
            "❓ Mujhe bhejo:\n"
            "• Video file \\(attach karo\\)\n"
            "• Video URL \\(catbox, direct link\\)\n"
            "• HLS link \\(\\.m3u8\\)\n\n"
            "/help se details dekho",
            parse_mode="MarkdownV2"
        )
        return

    url  = url_match.group(0)
    lo   = url.lower()
    kind = "📺 HLS stream" if ".m3u8" in lo else "🔗 Video URL"

    await update.message.reply_text(
        f"{kind} mili:\n`{url[:80]}`\n\n⏳ Process ho rahi hai\\.\\.\\.",
        parse_mode="MarkdownV2"
    )

    await process_convert(update, url, url.split("/")[-1][:40])

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

async def main():
    log.info("🎌 Starting Kenshin Converter Bot...")

    # Start HTTP server for HLS serving
    await start_http()

    # Build Telegram app
    tg_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("help",  cmd_help))
    tg_app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_file))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("✅ Bot handlers registered")
    log.info(f"✅ HLS base URL: {BASE_URL}")

    # Start polling
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)

    log.info("✅ Bot is polling for messages!")

    # Keep alive
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
