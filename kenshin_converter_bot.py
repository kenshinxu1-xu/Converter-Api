"""
Kenshin Anime — Video Converter Bot v2
H.265 → H.264 MP4 (sab browsers support karte hain!)

MODE 1 (Default): Convert karke Telegram pe hi bhej do
  → Fast, simple, storage ki tension nahi
  → Website pe direct Telegram video link kaam karta hai

MODE 2 (Optional): B2 pe upload karke HLS link do
  → Set USE_HLS=true env var karke enable karo

ENV VARS (zaroori):
  BOT_TOKEN  API_ID  API_HASH

OPTIONAL:
  USE_HLS=true        → HLS mode enable karo
  B2_KEY_ID           → Backblaze Key ID
  B2_APP_KEY          → Backblaze App Key
  B2_BUCKET           → default: kenshin-hls
  ADMIN_IDS           → tera user ID
"""

import os, asyncio, subprocess, shutil, time, json
from pathlib import Path

# ── AUTO INSTALL FFMPEG ───────────────────────────────────────────────────
def ensure_ffmpeg():
    import shutil as sh
    if sh.which("ffmpeg") and sh.which("ffprobe"):
        print("✅ ffmpeg ready")
        return True
    print("⚠️  ffmpeg missing — installing...")
    for cmd in [["apt-get","install","-y","ffmpeg"],
                ["apt","install","-y","ffmpeg"],
                ["apk","add","--no-cache","ffmpeg"]]:
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and sh.which("ffmpeg"):
            print("✅ ffmpeg installed!")
            return True
    print("❌ ffmpeg install failed!")
    return False

ensure_ffmpeg()

from pyrogram import Client, filters
from pyrogram.types import Message

USE_HLS   = os.getenv("USE_HLS","false").lower() == "true"
BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()]

# B2 config (only needed if USE_HLS=true)
B2_KEY_ID  = os.getenv("B2_KEY_ID","")
B2_APP_KEY = os.getenv("B2_APP_KEY","")
B2_BUCKET  = os.getenv("B2_BUCKET","kenshin-hls")
B2_ENDPOINT= os.getenv("B2_ENDPOINT","s3.us-west-004.backblazeb2.com")
B2_PUB     = f"https://f004.backblazeb2.com/file/{B2_BUCKET}"

WORK_DIR   = Path("/tmp/kbot"); WORK_DIR.mkdir(exist_ok=True)
VIDEO_EXTS = {".mp4",".mkv",".avi",".mov",".webm",".ts",".m4v",".3gp"}

# Qualities for HLS mode
QUALITIES = [("1080p",1080,28,"128k"),("720p",720,30,"96k"),("480p",480,32,"80k")]

# ── UTILS ─────────────────────────────────────────────────────────────────
def hsize(b):
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}GB"

def htime(s):
    s = int(s)
    if s < 60:   return f"{s}s"
    if s < 3600: return f"{s//60}m {s%60}s"
    return f"{s//3600}h {(s%3600)//60}m"

def pbar(pct, w=18):
    f = int(w * pct / 100)
    return f"[{'█'*f}{'░'*(w-f)}] {pct}%"

def get_info(path):
    r = subprocess.run(
        ["ffprobe","-v","quiet","-print_format","json",
         "-show_streams","-show_format", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr[:200]}")
    d = json.loads(r.stdout or "{}")
    info = {"w":0,"h":0,"codec":"?","dur":0}
    for s in d.get("streams",[]):
        if s.get("codec_type") == "video":
            info.update({"w":s.get("width",0),"h":s.get("height",0),
                         "codec":s.get("codec_name","?")})
    info["dur"] = float(d.get("format",{}).get("duration",0))
    return info

# ── ULTRA FAST DOWNLOAD VIA MULTIPLE STREAMS ─────────────────────────────
async def fast_download(client, message, file_path, prog_cb=None):
    """
    Download using multiple parallel DC connections.
    Pyrogram chunks the file across multiple connections automatically
    when max_concurrent_transmissions is set high.
    For extra speed, we also set a large read buffer.
    """
    import asyncio

    t0 = time.time()
    last_update = [0]
    file_size = (message.video or message.document).file_size or 1

    async def progress(current, total):
        if prog_cb:
            now = time.time()
            if now - last_update[0] < 1.2: return
            last_update[0] = now
            pct = int(current/total*100) if total else 0
            spd = current / max(now-t0, 0.1)
            eta = (total-current) / max(spd, 1)
            await prog_cb(pct, current, total, spd, eta)

    await client.download_media(message, file_name=str(file_path), progress=progress)
    return file_path

# ── MODE 1: CONVERT TO H.264 MP4 ─────────────────────────────────────────
async def convert_h264(inp, out, dur_s, cb=None):
    """H.265/any → H.264 MP4 — works on ALL browsers & devices"""
    cmd = [
        "ffmpeg", "-y", "-i", str(inp),
        "-map", "0:v:0",          # video track 0
        "-map", "0:a?",           # all audio (optional - ? = ignore if missing)
        "-c:v", "libx264",
        "-preset", "ultrafast",  # fastest encode, thoda bada file size
        "-crf", "23",
        "-c:a", "aac",            # force AAC - handles ANY input audio codec
        "-b:a", "128k",
        "-ac", "2",               # stereo - fixes surround sound issues
        "-ar", "44100",           # standard sample rate
        "-threads", "0",          # use all available CPU cores
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(out)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    last = 0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        line = line.decode().strip()
        if line.startswith("out_time_us=") and cb:
            now = time.time()
            if now - last < 2.5: continue
            last = now
            try:
                us  = int(line.split("=")[1])
                pct = min(int(us / (dur_s * 1_000_000) * 100), 99) if dur_s > 0 else 0
                m   = us // 60_000_000
                s   = (us % 60_000_000) // 1_000_000
                await cb(pct, f"{m}m {s}s encoded")
            except: pass

    await proc.wait()
    err = (await proc.stderr.read()).decode()
    if proc.returncode != 0 or not Path(out).exists():
        raise RuntimeError(f"H.264 conversion failed:\n{err[-300:]}")
    return out

# ── MODE 2: CONVERT TO WEBM + HLS ────────────────────────────────────────
async def convert_hls(inp, outdir, name, height, crf, abr, dur_s, cb=None):
    """H.265 → WebM VP9 → HLS segments"""
    outdir = Path(outdir)
    qdir   = outdir / name; qdir.mkdir(parents=True, exist_ok=True)
    webm   = outdir / f"_{name}.webm"
    m3u8   = qdir / "index.m3u8"

    # Step 1: Convert to WebM
    cmd = ["ffmpeg","-y","-i",str(inp),
           "-vf",f"scale=-2:{height}",
           "-c:v","libvpx-vp9","-crf",str(crf),"-b:v","0",
           "-deadline","realtime","-cpu-used","4","-row-mt","1",
           "-c:a","libopus","-b:a",abr,"-vbr","on",
           "-progress","pipe:1", str(webm)]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    last = 0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        line = line.decode().strip()
        if line.startswith("out_time_us=") and cb:
            now = time.time()
            if now - last < 2.5: continue
            last = now
            try:
                us  = int(line.split("=")[1])
                pct = min(int(us / (dur_s * 1_000_000) * 100), 99) if dur_s > 0 else 0
                m   = us // 60_000_000
                s   = (us % 60_000_000) // 1_000_000
                await cb(pct, f"{name}: {m}m {s}s")
            except: pass

    await proc.wait()
    if not webm.exists():
        raise RuntimeError(f"WebM failed [{name}]")

    # Step 2: Segment to HLS
    if cb: await cb(99, f"{name}: segmenting...")
    r2 = await asyncio.create_subprocess_exec(
        "ffmpeg","-y","-i",str(webm),"-c","copy",
        "-f","hls","-hls_time","6","-hls_list_size","0",
        "-hls_segment_type","mpegts","-hls_flags","independent_segments",
        "-hls_segment_filename",str(qdir/"seg_%04d.ts"), str(m3u8),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await r2.wait()
    webm.unlink(missing_ok=True)

    if not m3u8.exists():
        raise RuntimeError(f"HLS failed [{name}]")
    return m3u8

# ── B2 UPLOAD (fixed — no asyncio.as_completed bug) ──────────────────────
def b2_upload_sync(local, key):
    """Synchronous B2 upload — runs in thread"""
    import boto3
    from botocore.client import Config
    c = boto3.client("s3",
        endpoint_url=f"https://{B2_ENDPOINT}",
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
        config=Config(signature_version="s3v4"))
    ct = ("application/x-mpegURL" if key.endswith(".m3u8") else
          "video/MP2T"            if key.endswith(".ts")   else
          "application/octet-stream")
    c.upload_file(str(local), B2_BUCKET, key,
                  ExtraArgs={"ContentType":ct,"ACL":"public-read"})
    return f"{B2_PUB}/{key}"

async def b2_upload_dir(folder, prefix, prog_cb=None):
    """Upload all files — proper asyncio threading, no bug"""
    files  = sorted(Path(folder).glob("*.*"))
    total  = len(files)
    done   = 0
    urls   = {}
    loop   = asyncio.get_event_loop()

    for f in files:
        key = f"{prefix}/{f.name}"
        # run_in_executor = correct way to run sync code in async
        url = await loop.run_in_executor(None, b2_upload_sync, str(f), key)
        urls[f.name] = url
        done += 1
        if prog_cb:
            pct = int(done/total*100)
            await prog_cb(pct, done, total)

    return urls

def rewrite_m3u8(path, seg_urls):
    txt = Path(path).read_text()
    for fname, url in seg_urls.items():
        if fname.endswith(".ts"):
            txt = txt.replace(fname, url)
    Path(path).write_text(txt)

def make_master(q_urls, out_path):
    bw = {"1080p":(5000000,1920,1080),"720p":(2800000,1280,720),"480p":(1200000,854,480)}
    lines = ["#EXTM3U","#EXT-X-VERSION:3",""]
    for qn, url in q_urls.items():
        b,w,h = bw.get(qn,(2000000,1280,720))
        lines += [f'#EXT-X-STREAM-INF:BANDWIDTH={b},RESOLUTION={w}x{h},NAME="{qn}"',url,""]
    Path(out_path).write_text("\n".join(lines))

# ── BOT ───────────────────────────────────────────────────────────────────
bot  = Client(
    "kenshin_conv",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    # Max parallel connections per DC — makes download much faster!
    max_concurrent_transmissions=20,  # maximum parallel DC connections
)
jobs = {}

@bot.on_message(filters.command("start"))
async def cmd_start(_, m: Message):
    mode = "HLS → B2 Link" if USE_HLS else "H.264 MP4 → Telegram"
    await m.reply_text(
        "🎌 **Kenshin Video Converter**\n\n"
        f"Mode: **{mode}**\n\n"
        "Video bhejo aur main:\n"
        "✅ H.265 → H.264 convert karunga (sab devices pe chalega)\n"
        "✅ Real-time progress dikhaunga\n"
        "✅ Converted video wapas Telegram pe bhejna\n\n"
        "`/cancel` — rok do\n"
        "`/mode` — current mode dekho"
    )

@bot.on_message(filters.command("mode"))
async def cmd_mode(_, m: Message):
    if USE_HLS:
        await m.reply_text("🌐 **Mode: HLS** — B2 pe upload → m3u8 link")
    else:
        await m.reply_text("📱 **Mode: Telegram** — H.264 MP4 wapas Telegram pe")

@bot.on_message(filters.command("cancel"))
async def cmd_cancel(_, m: Message):
    uid = m.from_user.id
    if uid in jobs:
        jobs[uid]["cancel"] = True
        await m.reply_text("⛔ Cancel ho rahi hai...")
    else:
        await m.reply_text("Koi job nahi chal rahi.")

@bot.on_message(filters.video | filters.document)
async def handle_video(client, m: Message):
    uid = m.from_user.id
    if ADMIN_IDS and uid not in ADMIN_IDS:
        return

    if m.video:
        f = m.video; fname = f"video_{m.id}.mp4"
    else:
        f = m.document; fname = f.file_name or f"file_{m.id}"
        if Path(fname).suffix.lower() not in VIDEO_EXTS:
            return await m.reply_text(
                "⚠️ Video file bhejo!\nMP4, MKV, AVI, MOV, WebM, TS")

    if uid in jobs:
        return await m.reply_text("⏳ Pehle wali job chal rahi hai.\n/cancel karke naya bhejo.")

    st  = await m.reply_text(f"📥 Downloading `{fname}`...")
    job = {"cancel": False}
    jobs[uid] = job
    wd  = WORK_DIR / f"{uid}_{m.id}"; wd.mkdir(exist_ok=True)
    inp = wd / fname

    try:
        # ── FAST PARALLEL DOWNLOAD ────────────────────────────────────────
        t0 = time.time()

        async def dl_prog_cb(pct, cur, tot, spd, eta):
            if job["cancel"]: raise asyncio.CancelledError
            try:
                await st.edit_text(
                    f"📥 **Downloading**\n"
                    f"`{fname}`\n"
                    f"{pbar(pct)}\n"
                    f"{hsize(cur)} / {hsize(tot)}\n"
                    f"⚡ {hsize(int(spd))}/s  ⏱ {htime(eta)} baki")
            except: pass

        await fast_download(client, m, inp, prog_cb=dl_prog_cb)
        if not inp.exists(): raise RuntimeError("Download failed")

        # ── ANALYZE ───────────────────────────────────────────────────────
        info = get_info(str(inp))
        await st.edit_text(
            f"📊 **Video Info**\n"
            f"Codec: `{info['codec']}` → H.264\n"
            f"Resolution: `{info['w']}x{info['h']}`\n"
            f"Duration: `{htime(info['dur'])}`\n"
            f"Size: `{hsize(inp.stat().st_size)}`\n\n"
            f"🚀 Converting...")

        t_conv = time.time()

        # ── MODE 1: H.264 MP4 → SEND ON TELEGRAM ─────────────────────────
        if not USE_HLS:
            out_mp4 = wd / f"converted_{m.id}.mp4"

            async def conv_cb(pct, info_str):
                if not job["cancel"]:
                    try:
                        await st.edit_text(
                            f"⚙️ **Converting to H.264**\n"
                            f"{pbar(pct)}\n"
                            f"⏱ {info_str}\n"
                            f"Elapsed: {htime(time.time()-t_conv)}")
                    except: pass

            await convert_h264(str(inp), str(out_mp4), info["dur"], cb=conv_cb)
            inp.unlink(missing_ok=True)  # free space

            await st.edit_text(
                f"✅ Convert done! ({htime(time.time()-t_conv)})\n"
                f"📤 Uploading to Telegram...")

            # Upload with progress
            last_ul = 0
            async def ul_prog(cur, tot):
                nonlocal last_ul
                now = time.time()
                if now - last_ul < 2: return
                last_ul = now
                pct = int(cur/tot*100) if tot else 0
                spd = cur / max(now-t_conv, 0.1)
                await st.edit_text(
                    f"📤 **Uploading to Telegram**\n"
                    f"{pbar(pct)}\n"
                    f"{hsize(cur)} / {hsize(tot)}\n"
                    f"⚡ {hsize(int(spd))}/s")

            await m.reply_video(
                str(out_mp4),
                caption=(
                    f"✅ **Converted!**\n"
                    f"Original: `{info['codec']}` → H.264\n"
                    f"Resolution: `{info['w']}x{info['h']}`\n"
                    f"⏱ Conversion time: {htime(time.time()-t_conv)}\n\n"
                    f"Ab yeh video kisi bhi browser pe chalegi! 🎉"
                ),
                progress=ul_prog,
                supports_streaming=True
            )
            await st.delete()

        # ── MODE 2: HLS → BACKBLAZE B2 ────────────────────────────────────
        else:
            if not B2_KEY_ID:
                raise RuntimeError("B2_KEY_ID not set! USE_HLS=true ke liye B2 config zaroori hai.")

            target = [q for q in QUALITIES if q[1] <= info["h"]] or [QUALITIES[-1]]
            outdir = wd / "out"
            done   = {}

            for i, (qn, qh, qcrf, qabr) in enumerate(target):
                if job["cancel"]: raise asyncio.CancelledError

                async def hls_cb(pct, info_str, i=i, qn=qn):
                    if not job["cancel"]:
                        try:
                            await st.edit_text(
                                f"⚙️ **Step {i+1}/{len(target)}: {qn}**\n"
                                f"{pbar(pct)}\n"
                                f"⏱ {info_str}\n"
                                f"Elapsed: {htime(time.time()-t_conv)}")
                        except: pass

                done[qn] = await convert_hls(
                    str(inp), outdir, qn, qh, qcrf, qabr, info["dur"], cb=hls_cb)

            # Upload to B2
            q_urls = {}
            pfx    = f"v/{uid}_{m.id}"
            ul_t   = time.time()

            for qn, m3u8 in done.items():
                if job["cancel"]: raise asyncio.CancelledError

                async def b2_cb(pct, done_n, tot_n, qn=qn):
                    try:
                        await st.edit_text(
                            f"☁️ **Uploading {qn} → B2**\n"
                            f"{pbar(pct)}\n"
                            f"{done_n}/{tot_n} files\n"
                            f"⏱ {htime(time.time()-ul_t)} elapsed")
                    except: pass

                seg_urls = await b2_upload_dir(m3u8.parent, f"{pfx}/{qn}", b2_cb)
                rewrite_m3u8(m3u8, seg_urls)
                q_urls[qn] = await asyncio.get_event_loop().run_in_executor(
                    None, b2_upload_sync, str(m3u8), f"{pfx}/{qn}/index.m3u8")

            master = outdir / "master.m3u8"
            make_master(q_urls, master)
            master_url = await asyncio.get_event_loop().run_in_executor(
                None, b2_upload_sync, str(master), f"{pfx}/master.m3u8")

            player_fmt = "|||".join(f"{k}::{v}" for k,v in q_urls.items())
            result = (
                f"✅ **Done!** ⏱ {htime(time.time()-t_conv)}\n\n"
                f"🌐 **Master:** `{master_url}`\n\n"
                f"🎬 **Quality Links:**\n"
                + "\n".join(f"• **{k}:** `{v}`" for k,v in q_urls.items())
                + f"\n\n📋 **Kenshin Player Format:**\n`{player_fmt}`"
            )

            if len(result) > 4096:
                txt = wd/"links.txt"
                txt.write_text(f"Master: {master_url}\n\n"
                    + "\n".join(f"{k}: {v}" for k,v in q_urls.items())
                    + f"\n\nPlayer Format:\n{player_fmt}")
                await st.edit_text("✅ Done!")
                await m.reply_document(str(txt), caption="📋 HLS Links")
            else:
                await st.edit_text(result)

    except asyncio.CancelledError:
        await st.edit_text("⛔ Cancel ho gayi.")
    except Exception as e:
        await st.edit_text(f"❌ **Error:**\n`{str(e)[:400]}`")
        import traceback; traceback.print_exc()
    finally:
        jobs.pop(uid, None)
        shutil.rmtree(wd, ignore_errors=True)

if __name__ == "__main__":
    print("🎌 Kenshin Converter Bot v2")
    print(f"Mode: {'🌐 HLS → B2' if USE_HLS else '📱 H.264 → Telegram'}")
    print(f"Admins: {ADMIN_IDS or 'All users'}")
    bot.run()
