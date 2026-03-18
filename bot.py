"""
KENSHIN VIDEO CONVERTER BOT v3 — bot.py
Library : python-telegram-bot v20
Output  : HLS stream link (.m3u8) — directly plays on website
Deploy  : Railway → set BOT_TOKEN and BASE_URL env variables
"""

import os, sys, asyncio, subprocess, shutil, uuid, json, time, math, re, logging
import multiprocessing
from pathlib import Path

import requests
from aiohttp import web
import aiofiles

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("KenshinBot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BASE_URL  = os.environ.get("BASE_URL", "").rstrip("/")
PORT      = int(os.environ.get("PORT", "8080"))

if not BOT_TOKEN: log.error("BOT_TOKEN not set!"); sys.exit(1)
if not BASE_URL:  log.error("BASE_URL not set!");  sys.exit(1)

TMP       = Path("/tmp/kenshin")
TMP.mkdir(parents=True, exist_ok=True)
JOBS: dict = {}
CPUS       = multiprocessing.cpu_count()

# ── utils ──────────────────────────────────────────────────────

def fmt(s) -> str:
    try:
        s = float(s)
        if math.isnan(s) or s < 0: return "0:00"
    except: return "0:00"
    h, m, sc = int(s//3600), int((s%3600)//60), int(s%60)
    return f"{h}:{m:02d}:{sc:02d}" if h else f"{m}:{sc:02d}"

def resolve_url(url: str) -> str:
    try:
        r = requests.head(url, allow_redirects=True, timeout=15,
                          headers={"User-Agent":"Mozilla/5.0"})
        return r.url
    except: return url

def get_info_sync(src: str) -> dict | None:
    real = resolve_url(src) if src.startswith("http") else src
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-print_format","json",
             "-show_streams","-show_format","-user_agent","Mozilla/5.0",real],
            capture_output=True, text=True, timeout=60)
        data = json.loads(r.stdout)
        vs   = next((s for s in data.get("streams",[]) if s["codec_type"]=="video"), None)
        as_  = next((s for s in data.get("streams",[]) if s["codec_type"]=="audio"), None)
        h    = int(vs.get("height",0)) if vs else 0
        vc   = (vs.get("codec_name","?") if vs else "?").lower()
        ac   = (as_.get("codec_name","?") if as_ else "?").lower()
        lbl  = ("8K" if h>=4320 else "4K" if h>=2160 else "2K" if h>=1440
                else "1080p" if h>=1080 else "720p" if h>=720
                else "480p"  if h>=480  else "360p"  if h>=360 else f"{h}p")
        return {"vc":vc,"ac":ac,"w":int(vs.get("width",0)) if vs else 0,"h":h,"label":lbl,
                "dur":float(data.get("format",{}).get("duration") or 0),
                "bad":(vc not in ("h264","avc1","vp8","vp9","av1") or
                       ac not in ("aac","mp3","opus","vorbis","flac"))}
    except Exception as e:
        log.error(f"[INFO] {e}"); return None

def download_sync(url: str, dest: str, q: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    real  = resolve_url(url)
    r     = requests.get(real, stream=True, timeout=30, headers={"User-Agent":"Mozilla/5.0"})
    r.raise_for_status()
    total, done, last = int(r.headers.get("content-length",0)), 0, 0.0
    with open(dest,"wb") as f:
        for chunk in r.iter_content(512*1024):
            if chunk:
                f.write(chunk); done += len(chunk)
                now = time.time()
                if total and now-last >= 3:
                    last = now
                    asyncio.run_coroutine_threadsafe(q.put((done,total)), loop)
    asyncio.run_coroutine_threadsafe(q.put(None), loop)

def convert_sync(src: str, out_dir: Path, q: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    m3u8 = out_dir / "index.m3u8"
    cmd  = [
        "ffmpeg","-y","-loglevel","info",
        "-user_agent","Mozilla/5.0","-i",src,
        "-c:v","libx264","-preset","ultrafast","-crf","23",
        "-profile:v","baseline","-level:v","3.1","-pix_fmt","yuv420p",
        "-threads",str(CPUS),"-g","48","-sc_threshold","0",
        "-c:a","aac","-b:a","128k","-ac","2","-ar","44100",
        "-f","hls","-hls_time","6","-hls_list_size","0",
        "-hls_segment_type","mpegts","-hls_flags","independent_segments",
        "-hls_segment_filename",str(out_dir/"seg%04d.ts"), str(m3u8),
    ]
    proc   = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                              universal_newlines=True)
    dur    = 0.0; last_p = -1; last_t = 0.0
    for line in proc.stderr:
        if not dur and "Duration:" in line:
            try:
                t = line.split("Duration:")[1].split(",")[0].strip()
                h,m,s = t.split(":"); dur = int(h)*3600+int(m)*60+float(s)
            except: pass
        if "time=" in line and dur > 0:
            try:
                t   = line.split("time=")[1].split(" ")[0].strip()
                h,m,s = t.split(":"); cur = int(h)*3600+int(m)*60+float(s)
                pct = min(99,int(cur/dur*100))
                segs = len(list(out_dir.glob("*.ts")))
                now  = time.time()
                if pct != last_p and now-last_t >= 5:
                    last_p, last_t = pct, now
                    asyncio.run_coroutine_threadsafe(q.put((pct,cur,dur,segs)), loop)
            except: pass
    proc.wait()
    if proc.returncode != 0:
        asyncio.run_coroutine_threadsafe(q.put(RuntimeError(f"FFmpeg code {proc.returncode}")), loop)
    else:
        asyncio.run_coroutine_threadsafe(q.put(None), loop)

# ── HTTP server ────────────────────────────────────────────────

async def hls_handler(req: web.Request) -> web.Response:
    job = JOBS.get(req.match_info["jid"])
    if not job: return web.Response(status=404, text="Expired")
    fp  = Path(job["dir"]) / Path(req.match_info["name"]).name
    if not fp.exists(): return web.Response(status=404, text="Not ready")
    mime = "application/vnd.apple.mpegurl" if fp.suffix==".m3u8" else "video/mp2t"
    async with aiofiles.open(fp,"rb") as f: data = await f.read()
    return web.Response(body=data, headers={
        "Content-Type":mime, "Access-Control-Allow-Origin":"*", "Cache-Control":"no-cache"})

async def start_http():
    app = web.Application()
    app.router.add_get("/", lambda r: web.json_response({"status":"ok","jobs":len(JOBS)}))
    app.router.add_get("/hls/{jid}/{name}", hls_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner,"0.0.0.0",PORT).start()
    log.info(f"HTTP :{PORT}")

# ── core pipeline ──────────────────────────────────────────────

async def do_convert(update: Update, src: str, name: str = ""):
    loop   = asyncio.get_running_loop()
    jid    = uuid.uuid4().hex[:10]
    dl_dir = None
    status = await update.message.reply_text("🔍 Checking codec...")

    async def edit(t):
        try: await status.edit_text(t, parse_mode="Markdown")
        except: pass

    try:
        info = await loop.run_in_executor(None, get_info_sync, src)
        itxt = (f"📊 *Info:*\n• `{info['label']}` {info['w']}×{info['h']}\n"
                f"• Video: `{info['vc'].upper()}`  Audio: `{info['ac'].upper()}`\n"
                f"• Duration: `{fmt(info['dur'])}`\n\n") if info else f"`{name or src}`\n\n"

        if info and not info["bad"]:
            msg = itxt + "✅ *Already H.264+AAC — no conversion needed!*"
            if src.startswith("http"): msg += f"\n\n🔗 Direct URL:\n`{src}`"
            await edit(msg); return

        # Download URL first
        actual = src
        if src.startswith("http"):
            await edit(itxt + "📥 *Downloading...*\n`[░░░░░░░░░░] 0%`")
            dl_dir = TMP / f"dl_{jid}"; dl_dir.mkdir(parents=True, exist_ok=True)
            lo     = src.lower().split("?")[0]
            ext    = ".mkv" if ".mkv" in lo else ".mp4"
            actual = str(dl_dir / f"input{ext}")
            dlq    = asyncio.Queue()
            dl_t0  = time.time()

            t = loop.run_in_executor(None, download_sync, src, actual, dlq, loop)
            while True:
                item = await dlq.get()
                if item is None: break
                if isinstance(item, Exception): raise item
                done, total = item
                pct = int(done/total*100); bar = "█"*(pct//10)+"░"*(10-pct//10)
                spd = done/1024/1024/(time.time()-dl_t0+.01)
                await edit(itxt + f"📥 *Downloading...*\n`[{bar}] {pct}%`\n"
                           f"`{done/1024/1024:.0f}/{total/1024/1024:.0f} MB` ⚡ `{spd:.1f} MB/s`")
            await t

            await edit(itxt + "✅ *Downloaded!*\n⚙️ *Converting...*\n`[░░░░░░░░░░] 0%`")
        else:
            await edit(itxt + "⚙️ *Converting...*\n`[░░░░░░░░░░] 0%`")

        # Convert
        out = TMP / jid
        if out.exists(): shutil.rmtree(out)
        out.mkdir(parents=True)
        JOBS[jid] = {"dir":str(out),"status":"processing","started":time.time()}

        cvq  = asyncio.Queue()
        cv_t0 = time.time()
        ct   = loop.run_in_executor(None, convert_sync, actual, out, cvq, loop)

        while True:
            item = await cvq.get()
            if item is None: break
            if isinstance(item, Exception): raise item
            pct, cur, dur, segs = item
            bar = "█"*(pct//10)+"░"*(10-pct//10)
            spd = cur/(time.time()-cv_t0+.01)
            eta = (dur-cur)/spd if spd>0 else 0
            await edit(itxt + f"⚙️ *Converting (ultrafast)*\n`[{bar}] {pct}%`\n"
                       f"⏱ `{fmt(cur)} / {fmt(dur)}`\n"
                       f"📦 Segments: `{segs}`\n"
                       f"⚡ `{spd:.1f}x` real-time | ETA: `{fmt(eta)}`")
        await ct

        JOBS[jid]["status"] = "done"
        segs = len(list(out.glob("*.ts")))
        url  = f"{BASE_URL}/hls/{jid}/index.m3u8"

        await edit(itxt + f"✅ *Done\\!* 🎌\n\n"
                   f"📦 Segments: `{segs}` | ⏳ Valid: 2h\n\n"
                   f"🔗 *HLS Play URL:*\n`{url}`\n\n"
                   f"👆 Admin panel mein episode URL paste karo\\!\n"
                   f"Chrome/Firefox/Safari sab pe chalegi ✅")

        async def _cleanup():
            await asyncio.sleep(7200)
            JOBS.pop(jid, None); shutil.rmtree(str(out), ignore_errors=True)
        asyncio.create_task(_cleanup())

    except Exception as e:
        log.error(f"[CONVERT] {e}")
        await edit(f"❌ *Error:*\n`{str(e)[:300]}`\n\n• URL accessible hai?\n• Format supported hai?")
    finally:
        if dl_dir and dl_dir.exists(): shutil.rmtree(str(dl_dir), ignore_errors=True)

# ── Telegram handlers ──────────────────────────────────────────

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎌 *Kenshin Video Converter Bot*\n\n"
        "Bhejo:\n• 🎬 Video file ≤20MB\n• 🔗 catbox URL\n• 📺 HLS .m3u8 link\n\n"
        "Convert: H.265→H.264 ✅  AC3/DTS→AAC ✅  MKV→HLS ✅\n\n"
        "Return: 🔗 HLS link — website pe paste karo\\!",
        parse_mode="MarkdownV2")

async def cmd_help(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Help*\n\n1\\. Video attach ≤20MB\n"
        "2\\. catbox\\.moe URL bhejo\n3\\. \\.m3u8 HLS link bhejo\n\n"
        "20MB\\+ → catbox\\.moe pe upload → URL bhejo",
        parse_mode="MarkdownV2")

async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg   = update.message
    media = msg.video or msg.document
    if not media: return
    if msg.document:
        fn = (msg.document.file_name or "").lower()
        if not any(fn.endswith(e) for e in (".mp4",".mkv",".avi",".webm",".mov",".flv",".m4v",".ts")):
            await msg.reply_text("⚠️ Sirf video files: MP4, MKV, AVI, WebM"); return
    fn   = getattr(media,"file_name",None) or "video.mp4"
    size = (getattr(media,"file_size",0) or 0)/1024/1024
    if size > 20:
        await msg.reply_text(
            f"⚠️ *{size:.0f} MB — limit 20MB*\n\ncatbox\\.moe pe upload karo → URL bhejo ✅",
            parse_mode="MarkdownV2"); return
    st   = await msg.reply_text(f"📥 Downloading `{fn}`...", parse_mode="Markdown")
    jid  = uuid.uuid4().hex[:8]
    dld  = TMP/f"dl_{jid}"; dld.mkdir(parents=True, exist_ok=True)
    dest = str(dld/f"input{Path(fn).suffix or '.mp4'}")
    try:
        f = await ctx.bot.get_file(media.file_id)
        await f.download_to_drive(dest)
        await st.edit_text("✅ Downloaded! Converting...", parse_mode="Markdown")
        await do_convert(update, dest, fn)
    except Exception as e:
        log.error(f"[FILE] {e}")
        await st.edit_text(f"❌ `{e}`", parse_mode="Markdown")
    finally:
        shutil.rmtree(str(dld), ignore_errors=True)

async def handle_text(update: Update, _: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    m   = re.search(r'https?://\S+', txt)
    if not m:
        await update.message.reply_text("❓ URL bhejo ya /help dekho"); return
    url  = m.group(0)
    kind = "📺 HLS" if ".m3u8" in url.lower() else "🔗 URL"
    await update.message.reply_text(f"{kind}: `{url[:70]}`\n⏳ Processing...", parse_mode="Markdown")
    await do_convert(update, url, url.split("/")[-1][:40])

# ── main ───────────────────────────────────────────────────────

async def main():
    await start_http()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info(f"Bot polling ✅  BASE_URL={BASE_URL}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
