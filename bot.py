"""
Kenshin Anime — Video Converter Bot
Video → WebM VP9 → HLS → Backblaze B2

SETUP:
  apt install ffmpeg       ← ffprobe bhi iske saath aata hai
  pip install pyrogram tgcrypto boto3
  Set 5 env vars → python kenshin_converter_bot.py

ENV VARS (sirf 5 zaroori):
  BOT_TOKEN  API_ID  API_HASH  B2_KEY_ID  B2_APP_KEY

OPTIONAL:
  B2_BUCKET=kenshin-hls
  ADMIN_IDS=123456789
"""

import os, asyncio, subprocess, shutil, time, json, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ── AUTO INSTALL FFMPEG IF MISSING ───────────────────────────────────────
def ensure_ffmpeg():
    ff  = shutil.which("ffmpeg")
    ffp = shutil.which("ffprobe")
    if ff and ffp:
        print(f"✅ ffmpeg: {ff}")
        print(f"✅ ffprobe: {ffp}")
        return
    print("⚠️  ffmpeg/ffprobe not found — trying to install...")
    # Try different package managers
    for cmd in [
        ["apt-get","install","-y","ffmpeg"],
        ["apt","install","-y","ffmpeg"],
        ["apk","add","--no-cache","ffmpeg"],
    ]:
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and shutil.which("ffmpeg"):
            print("✅ ffmpeg installed!")
            return
    # Last resort: download static binary
    print("⚠️  Package install failed, trying static binary...")
    import urllib.request, tarfile, os
    url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    try:
        bin_dir = Path("/usr/local/bin")
        tar_path = Path("/tmp/ffmpeg.tar.xz")
        urllib.request.urlretrieve(url, str(tar_path))
        with tarfile.open(str(tar_path)) as tar:
            for member in tar.getmembers():
                if member.name.endswith("/ffmpeg") or member.name.endswith("/ffprobe"):
                    member.name = Path(member.name).name
                    tar.extract(member, str(bin_dir))
                    os.chmod(str(bin_dir/member.name), 0o755)
        if shutil.which("ffmpeg"):
            print("✅ ffmpeg static binary installed!")
            return
    except Exception as e:
        print(f"Static binary failed: {e}")
    print("❌ Could not install ffmpeg! Add to nixpacks.toml or Dockerfile.")

ensure_ffmpeg()

from pyrogram import Client, filters
from pyrogram.types import Message

try:
    import boto3
    from botocore.client import Config
    HAS_B2 = True
except ImportError:
    HAS_B2 = False

# ── CONFIG ────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ["BOT_TOKEN"]
API_ID     = int(os.environ["API_ID"])
API_HASH   = os.environ["API_HASH"]
B2_KEY_ID  = os.environ["B2_KEY_ID"]
B2_APP_KEY = os.environ["B2_APP_KEY"]
B2_BUCKET  = os.getenv("B2_BUCKET", "kenshin-hls")
B2_ENDPOINT= os.getenv("B2_ENDPOINT", "s3.us-west-004.backblazeb2.com")
ADMIN_IDS  = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()]
B2_PUB     = f"https://f004.backblazeb2.com/file/{B2_BUCKET}"

WORK_DIR = Path("/tmp/kbot"); WORK_DIR.mkdir(exist_ok=True)
VIDEO_EXTS = {".mp4",".mkv",".avi",".mov",".webm",".ts",".m4v",".3gp"}
QUALITIES  = [("1080p",1080,31,"128k"),("720p",720,33,"96k"),("480p",480,35,"80k")]

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

def progress_bar(pct, width=16):
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct}%"

def get_info(path):
    """Get video info using ffprobe"""
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

# ── B2 FAST PARALLEL UPLOAD ───────────────────────────────────────────────
def _make_b2():
    return boto3.client("s3",
        endpoint_url=f"https://{B2_ENDPOINT}",
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
        config=Config(signature_version="s3v4",
                      max_pool_connections=20))   # connection pool

def b2_upload_one(args):
    """Upload single file — runs in thread"""
    local, key = args
    ct = ("application/x-mpegURL" if key.endswith(".m3u8") else
          "video/MP2T"            if key.endswith(".ts")   else
          "application/octet-stream")
    _make_b2().upload_file(local, B2_BUCKET, key,
        ExtraArgs={"ContentType":ct,"ACL":"public-read"})
    return f"{B2_PUB}/{key}"

async def b2_upload_dir_parallel(folder, prefix, prog_cb=None):
    """Upload all files in parallel using thread pool — MUCH faster!"""
    files = sorted(Path(folder).glob("*.ts")) + sorted(Path(folder).glob("*.m3u8"))
    tasks = [(str(f), f"{prefix}/{f.name}") for f in files]
    total = len(tasks)
    done  = 0
    urls  = {}

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=8) as pool:   # 8 parallel uploads
        futures = {loop.run_in_executor(pool, b2_upload_one, t): t for t in tasks}
        for fut in asyncio.as_completed(futures.keys()):
            local, key = futures[fut]
            fname = Path(local).name
            url   = await fut
            urls[fname] = url
            done += 1
            if prog_cb:
                pct = int(done/total*100)
                await prog_cb(pct, done, total)

    return urls

# ── FFMPEG CONVERT + SEGMENT ──────────────────────────────────────────────
async def convert(inp, outdir, name, height, crf, abr, dur_s, cb=None):
    """
    inp     → input video path
    outdir  → output base dir
    dur_s   → total duration in seconds (for progress %)
    cb      → async callback(stage_msg, pct)
    """
    outdir = Path(outdir)
    qdir   = outdir / name;  qdir.mkdir(parents=True, exist_ok=True)
    webm   = outdir / f"_{name}.webm"
    m3u8   = qdir   / "index.m3u8"

    # ── Step 1: Convert to WebM VP9 ──────────────────────────────────────
    cmd = [
        "ffmpeg","-y","-i", str(inp),
        "-vf",    f"scale=-2:{height}",
        "-c:v",   "libvpx-vp9",
        "-crf",   str(crf), "-b:v","0",
        "-deadline","realtime", "-cpu-used","4", "-row-mt","1",
        "-c:a",   "libopus", "-b:a", abr, "-vbr","on",
        "-progress","pipe:1",
        str(webm)
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)

    last_cb = 0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        line = line.decode().strip()
        if line.startswith("out_time_us="):
            now = time.time()
            if now - last_cb < 2.5: continue
            last_cb = now
            try:
                us  = int(line.split("=")[1])
                pct = min(int(us / (dur_s * 1_000_000) * 100), 99) if dur_s > 0 else 0
                m   = us // 60_000_000
                s   = (us % 60_000_000) // 1_000_000
                bar = progress_bar(pct)
                if cb: await cb(f"⚙️ Converting {name}\n{bar}\n⏱ {m}m{s}s encoded", pct)
            except: pass

    await proc.wait()
    if not webm.exists():
        err = (await proc.stderr.read()).decode()[-300:]
        raise RuntimeError(f"WebM failed [{name}]: {err}")

    if cb: await cb(f"📦 Segmenting {name} → HLS...", 99)

    # ── Step 2: Segment WebM → HLS ────────────────────────────────────────
    cmd2 = [
        "ffmpeg","-y","-i",str(webm),"-c","copy",
        "-f","hls","-hls_time","6","-hls_list_size","0",
        "-hls_segment_type","mpegts","-hls_flags","independent_segments",
        "-hls_segment_filename", str(qdir/"seg_%04d.ts"),
        str(m3u8)
    ]
    r2 = await asyncio.create_subprocess_exec(
        *cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await r2.wait()
    webm.unlink(missing_ok=True)

    if not m3u8.exists():
        err2 = (await r2.stderr.read()).decode()[-300:]
        raise RuntimeError(f"HLS failed [{name}]: {err2}")

    return m3u8

def rewrite_m3u8(path, seg_urls):
    txt = Path(path).read_text()
    for fname, url in seg_urls.items():
        if fname.endswith(".ts"):
            txt = txt.replace(fname, url)
    Path(path).write_text(txt)

def make_master(q_urls, out_path):
    bw = {"1080p":(5000000,1920,1080),"720p":(2800000,1280,720),"480p":(1200000,854,480)}
    lines = ["#EXTM3U","#EXT-X-VERSION:3",""]
    for qn,url in q_urls.items():
        b,w,h = bw.get(qn,(2000000,1280,720))
        lines += [f'#EXT-X-STREAM-INF:BANDWIDTH={b},RESOLUTION={w}x{h},NAME="{qn}"',url,""]
    Path(out_path).write_text("\n".join(lines))

# ── BOT ───────────────────────────────────────────────────────────────────
bot  = Client("kenshin_conv", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
jobs = {}   # uid → {"cancel": bool}

@bot.on_message(filters.command("start"))
async def cmd_start(_, m: Message):
    await m.reply_text(
        "🎌 **Kenshin Video Converter**\n\n"
        "Koi bhi video bhejo:\n"
        "✅ H.265/H.264 → WebM VP9\n"
        "✅ HLS segments (480p/720p/1080p)\n"
        "✅ Backblaze B2 fast parallel upload\n"
        "✅ Kenshin Player ready link\n\n"
        "`/cancel` — rok do"
    )

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

    # File detect
    if m.video:
        f = m.video;  fname = f"video_{m.id}.mp4"
    else:
        f = m.document; fname = f.file_name or f"file_{m.id}"
        if Path(fname).suffix.lower() not in VIDEO_EXTS:
            return await m.reply_text(
                "⚠️ Video file bhejo!\nMP4, MKV, AVI, MOV, WebM, TS support hai.")

    if uid in jobs:
        return await m.reply_text("⏳ Pehle wali job chal rahi hai.\n/cancel karke naya bhejo.")

    st  = await m.reply_text(f"📥 Downloading `{fname}`...")
    job = {"cancel": False}
    jobs[uid] = job
    wd  = WORK_DIR / f"{uid}_{m.id}";  wd.mkdir(exist_ok=True)
    inp = wd / fname

    try:
        # ── DOWNLOAD WITH PROGRESS ────────────────────────────────────────
        t0 = time.time(); last_dl = 0

        async def dl_prog(cur, tot):
            nonlocal last_dl
            if job["cancel"]: raise asyncio.CancelledError
            now = time.time()
            if now - last_dl < 2: return
            last_dl = now
            pct = int(cur/tot*100) if tot else 0
            spd = cur / max(now-t0, 0.1)
            eta = (tot-cur) / max(spd, 1)
            bar = progress_bar(pct)
            await st.edit_text(
                f"📥 **Downloading**\n"
                f"`{fname}`\n"
                f"{bar}\n"
                f"{hsize(cur)} / {hsize(tot)}\n"
                f"⚡ {hsize(int(spd))}/s  ⏱ {htime(eta)} baki")

        await client.download_media(m, file_name=str(inp), progress=dl_prog)
        if not inp.exists(): raise RuntimeError("Download failed")

        # ── ANALYZE ───────────────────────────────────────────────────────
        info = get_info(str(inp))
        await st.edit_text(
            f"📊 **Video Info**\n"
            f"Codec: `{info['codec']}` → WebM VP9\n"
            f"Res: `{info['w']}x{info['h']}`\n"
            f"Duration: `{htime(info['dur'])}`\n"
            f"Size: `{hsize(inp.stat().st_size)}`\n\n"
            f"🚀 Converting...")

        target = [q for q in QUALITIES if q[1] <= info["h"]] or [QUALITIES[-1]]
        outdir = wd / "out"
        done   = {}   # qname → m3u8 path
        t_conv = time.time()

        # ── CONVERT EACH QUALITY ──────────────────────────────────────────
        for i, (qn, qh, qcrf, qabr) in enumerate(target):
            if job["cancel"]: raise asyncio.CancelledError

            stage_start = time.time()
            async def cb(msg, pct, i=i, qn=qn):
                if not job["cancel"]:
                    try:
                        elapsed = htime(time.time() - t_conv)
                        await st.edit_text(
                            f"⚙️ **Step {i+1}/{len(target)}: {qn}**\n"
                            f"{msg}\n"
                            f"Total elapsed: {elapsed}")
                    except: pass

            done[qn] = await convert(
                str(inp), outdir, qn, qh, qcrf, qabr, info["dur"], cb=cb)

        # ── UPLOAD TO B2 (PARALLEL) ───────────────────────────────────────
        q_urls    = {}
        master_url = ""

        if HAS_B2 and B2_KEY_ID:
            pfx         = f"v/{uid}_{m.id}"
            total_segs  = sum(len(list((done[qn].parent).glob("*.ts"))) for qn in done)
            uploaded    = [0]   # mutable counter
            ul_start    = time.time()

            for qn, m3u8 in done.items():
                if job["cancel"]: raise asyncio.CancelledError

                qdir = m3u8.parent
                q_total = len(list(qdir.glob("*.ts"))) + 1   # +1 for m3u8

                async def ul_cb(pct, done_n, tot_n, qn=qn):
                    elapsed = htime(time.time() - ul_start)
                    bar = progress_bar(pct)
                    await st.edit_text(
                        f"☁️ **Uploading {qn} → B2**\n"
                        f"{bar}\n"
                        f"{done_n}/{tot_n} files\n"
                        f"⏱ {elapsed} elapsed")

                seg_urls = await b2_upload_dir_parallel(qdir, f"{pfx}/{qn}", ul_cb)

                # Rewrite m3u8 with CDN URLs
                rewrite_m3u8(m3u8, seg_urls)

                # Upload the updated m3u8
                m3u8_url = b2_upload_one((str(m3u8), f"{pfx}/{qn}/index.m3u8"))
                q_urls[qn] = m3u8_url

            # Master playlist
            master = outdir / "master.m3u8"
            make_master(q_urls, master)
            master_url = b2_upload_one((str(master), f"{pfx}/master.m3u8"))

        else:
            for qn, m3u8 in done.items():
                q_urls[qn] = str(m3u8)
            master_url = "⚠️ B2 not configured"

        # ── RESULT ────────────────────────────────────────────────────────
        player_fmt = "|||".join(f"{k}::{v}" for k,v in q_urls.items())
        total_time = htime(time.time() - t_conv)

        result = (
            f"✅ **Done!** ⏱ {total_time}\n\n"
            f"🎬 **Links:**\n"
            + "\n".join(f"• **{k}:** `{v}`" for k,v in q_urls.items())
            + (f"\n\n🌐 **Master:** `{master_url}`" if master_url and not master_url.startswith("⚠️") else "")
            + f"\n\n📋 **Kenshin Player Format:**\n_(Admin panel → Trailer URL mein paste karo)_\n\n"
            f"`{player_fmt}`"
        )

        if len(result) > 4096:
            txt = wd / "links.txt"
            txt.write_text(
                f"Master: {master_url}\n\n"
                + "\n".join(f"{k}: {v}" for k,v in q_urls.items())
                + f"\n\nKenshin Player Format:\n{player_fmt}"
            )
            await st.edit_text("✅ Done! Links file mein hain 👇")
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
    print("🎌 Kenshin Converter Bot starting...")
    print(f"B2 upload: {'✅ Parallel (8 threads)' if HAS_B2 and B2_KEY_ID else '❌ Not configured'}")
    print(f"Admins: {ADMIN_IDS or 'All users allowed'}")
    bot.run()
