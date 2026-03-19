"""
Kenshin Anime — Video Converter Bot
Video → WebM VP9 → HLS → Backblaze B2

SETUP:
  pip install pyrogram tgcrypto boto3
  Set 5 env vars (see below)
  python kenshin_converter_bot.py

ENV VARS (sirf 5):
  BOT_TOKEN   → @BotFather se
  API_ID      → my.telegram.org se
  API_HASH    → my.telegram.org se
  B2_KEY_ID   → Backblaze B2 Key ID
  B2_APP_KEY  → Backblaze B2 App Key

OPTIONAL:
  B2_BUCKET   → default: kenshin-hls
  ADMIN_IDS   → tera user ID (blank = sab allowed)
"""

import os, asyncio, subprocess, shutil, time, json
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

try:
    import boto3
    from botocore.client import Config
    HAS_B2 = True
except ImportError:
    HAS_B2 = False

# ── ONLY 5 REQUIRED ENV VARS ──────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APP_KEY= os.environ["B2_APP_KEY"]

# Optional (with defaults)
B2_BUCKET   = os.getenv("B2_BUCKET", "kenshin-hls")
B2_ENDPOINT = os.getenv("B2_ENDPOINT", "s3.us-west-004.backblazeb2.com")
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS","").split(",") if x.strip().isdigit()]

# CDN public URL auto-detect karta hai
B2_PUB = f"https://f004.backblazeb2.com/file/{B2_BUCKET}"

WORK_DIR = Path("/tmp/kbot"); WORK_DIR.mkdir(exist_ok=True)
VIDEO_EXTS = {".mp4",".mkv",".avi",".mov",".webm",".ts",".m4v",".3gp"}

# Quality: (name, height, crf, audio_br)
QUALITIES = [("1080p",1080,31,"128k"), ("720p",720,33,"96k"), ("480p",480,35,"80k")]

# ── UTILS ─────────────────────────────────────────────────────────────────
def hsize(b):
    for u in ["B","KB","MB","GB"]:
        if b < 1024: return f"{b:.1f}{u}"
        b /= 1024
    return f"{b:.1f}GB"

def htime(s):
    s=int(s)
    if s<60: return f"{s}s"
    if s<3600: return f"{s//60}m{s%60}s"
    return f"{s//3600}h{(s%3600)//60}m"

def get_info(path):
    r = subprocess.run(
        ["ffprobe","-v","quiet","-print_format","json","-show_streams","-show_format",path],
        capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    info = {"w":0,"h":0,"codec":"?","dur":0}
    for s in d.get("streams",[]):
        if s.get("codec_type")=="video":
            info.update({"w":s.get("width",0),"h":s.get("height",0),"codec":s.get("codec_name","?")})
    info["dur"] = float(d.get("format",{}).get("duration",0))
    return info

# ── B2 UPLOAD ─────────────────────────────────────────────────────────────
def b2_upload(local, key):
    if not HAS_B2: return ""
    c = boto3.client("s3",
        endpoint_url=f"https://{B2_ENDPOINT}",
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
        config=Config(signature_version="s3v4"))
    ct = ("application/x-mpegURL" if key.endswith(".m3u8") else
          "video/MP2T" if key.endswith(".ts") else "application/octet-stream")
    c.upload_file(local, B2_BUCKET, key, ExtraArgs={"ContentType":ct,"ACL":"public-read"})
    return f"{B2_PUB}/{key}"

# ── CONVERT + SEGMENT ─────────────────────────────────────────────────────
async def convert(inp, outdir, name, height, crf, abr, cb=None):
    outdir = Path(outdir)
    qdir = outdir/name; qdir.mkdir(parents=True, exist_ok=True)
    webm = outdir/f"_{name}.webm"
    m3u8 = qdir/"index.m3u8"

    if cb: await cb(f"⚙️ {name}: H.265 → WebM VP9...")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg","-y","-i",inp,
        "-vf",f"scale=-2:{height}",
        "-c:v","libvpx-vp9","-crf",str(crf),"-b:v","0",
        "-deadline","realtime","-cpu-used","4","-row-mt","1",
        "-c:a","libopus","-b:a",abr,"-vbr","on",
        "-progress","pipe:1", str(webm),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    last=0
    while True:
        line = await proc.stdout.readline()
        if not line: break
        line = line.decode().strip()
        if line.startswith("out_time_us=") and cb:
            now=time.time()
            if now-last > 4:
                last=now
                try:
                    us=int(line.split("=")[1])
                    m=us//60000000; s=(us%60000000)//1000000
                    await cb(f"⚙️ {name}: {m}m{s}s encoded...")
                except: pass
    await proc.wait()

    if not webm.exists():
        raise RuntimeError(f"WebM failed [{name}]")

    if cb: await cb(f"📦 {name}: Segmenting to HLS...")
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

def rewrite_m3u8(m3u8, seg_urls):
    txt = Path(m3u8).read_text()
    for fname, url in seg_urls.items():
        if fname.endswith(".ts"): txt = txt.replace(fname, url)
    Path(m3u8).write_text(txt)

def make_master(q_urls, master_path):
    bw = {"1080p":(5000000,1920,1080),"720p":(2800000,1280,720),"480p":(1200000,854,480)}
    lines = ["#EXTM3U","#EXT-X-VERSION:3",""]
    for qn, url in q_urls.items():
        b,w,h = bw.get(qn,(2000000,1280,720))
        lines += [f'#EXT-X-STREAM-INF:BANDWIDTH={b},RESOLUTION={w}x{h},NAME="{qn}"', url, ""]
    Path(master_path).write_text("\n".join(lines))

# ── BOT ───────────────────────────────────────────────────────────────────
bot = Client("kenshin_conv", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
jobs = {}

@bot.on_message(filters.command("start"))
async def start(_, m: Message):
    await m.reply_text(
        "🎌 **Kenshin Video Converter**\n\n"
        "Video bhejo (H.265/H.264/koi bhi format):\n\n"
        "✅ WebM VP9 mein convert hogi\n"
        "✅ HLS segments banenge (480p/720p/1080p)\n"
        "✅ Backblaze B2 pe upload hoga\n"
        "✅ Kenshin Player ready link milega\n\n"
        "`/cancel` — conversion rokne ke liye"
    )

@bot.on_message(filters.command("cancel"))
async def cancel(_, m: Message):
    uid = m.from_user.id
    if uid in jobs:
        jobs[uid]["cancel"] = True
        await m.reply_text("⛔ Cancel ho rahi hai...")
    else:
        await m.reply_text("Koi job nahi chal rahi.")

@bot.on_message(filters.video | filters.document)
async def handle(client, m: Message):
    uid = m.from_user.id
    if ADMIN_IDS and uid not in ADMIN_IDS:
        return

    if m.video:
        f = m.video; fname = f"video_{m.id}.mp4"
    else:
        f = m.document; fname = f.file_name or f"file_{m.id}"
        if Path(fname).suffix.lower() not in VIDEO_EXTS:
            return await m.reply_text("⚠️ Video file bhejo (MP4, MKV, AVI, MOV, WebM, TS)")

    if uid in jobs:
        return await m.reply_text("⏳ Pehle wali job chal rahi hai. /cancel karo pehle.")

    st = await m.reply_text(f"📥 Downloading `{fname}`...")
    job = {"cancel": False}
    jobs[uid] = job
    wd = WORK_DIR/f"{uid}_{m.id}"; wd.mkdir(exist_ok=True)
    inp = wd/fname

    try:
        # Download
        t0=time.time(); last_dl=0
        async def dl_prog(cur, tot):
            nonlocal last_dl
            if job["cancel"]: raise asyncio.CancelledError
            now=time.time()
            if now-last_dl < 2: return
            last_dl=now
            pct=int(cur/tot*100) if tot else 0
            spd=cur/max(now-t0,.1)
            await st.edit_text(
                f"📥 Downloading `{fname}`\n"
                f"{pct}% — {hsize(cur)}/{hsize(tot)}\n"
                f"⚡ {hsize(int(spd))}/s | ⏱ {htime((tot-cur)/max(spd,1))}")

        await client.download_media(m, file_name=str(inp), progress=dl_prog)
        if not inp.exists(): raise RuntimeError("Download failed")

        # Analyze
        info = get_info(str(inp))
        await st.edit_text(
            f"📊 **Info:**\n"
            f"Codec: `{info['codec']}` → WebM VP9\n"
            f"Res: `{info['w']}x{info['h']}`\n"
            f"Duration: `{htime(info['dur'])}`\n\n"
            f"🚀 Converting...")

        target = [q for q in QUALITIES if q[1]<=info["h"]] or [QUALITIES[-1]]
        outdir = wd/"out"
        done = {}
        t_conv = time.time()

        # Convert each quality
        for i,(qn,qh,qcrf,qabr) in enumerate(target):
            if job["cancel"]: raise asyncio.CancelledError
            async def cb(msg, i=i, qn=qn):
                if not job["cancel"]:
                    try:
                        await st.edit_text(
                            f"⚙️ **{qn}** ({i+1}/{len(target)})\n"
                            f"{msg}\n"
                            f"⏱ {htime(time.time()-t_conv)}")
                    except: pass
            done[qn] = await convert(str(inp), outdir, qn, qh, qcrf, qabr, cb=cb)

        # Upload to B2
        q_urls = {}
        if HAS_B2 and B2_KEY_ID:
            await st.edit_text("☁️ Uploading to Backblaze B2...")
            pfx = f"v/{uid}_{m.id}"
            for qn, m3u8 in done.items():
                if job["cancel"]: raise asyncio.CancelledError
                await st.edit_text(f"☁️ Uploading {qn}...")
                qdir = m3u8.parent
                seg_urls = {}
                for seg in sorted(qdir.glob("*.ts")):
                    seg_urls[seg.name] = b2_upload(str(seg), f"{pfx}/{qn}/{seg.name}")
                rewrite_m3u8(m3u8, seg_urls)
                q_urls[qn] = b2_upload(str(m3u8), f"{pfx}/{qn}/index.m3u8")

            master = outdir/"master.m3u8"
            make_master(q_urls, master)
            master_url = b2_upload(str(master), f"{pfx}/master.m3u8")
        else:
            for qn, m3u8 in done.items():
                q_urls[qn] = str(m3u8)
            master_url = "⚠️ B2 not configured"

        # Result
        player_fmt = "|||".join(f"{k}::{v}" for k,v in q_urls.items())
        result = (
            f"✅ **Done!** ⏱ {htime(time.time()-t_conv)}\n\n"
            f"🎬 **Links:**\n"
            + "\n".join(f"• **{k}:** `{v}`" for k,v in q_urls.items())
            + (f"\n\n🌐 **Master:** `{master_url}`" if not master_url.startswith("⚠️") else "")
            + f"\n\n📋 **Kenshin Player Format:**\n`{player_fmt}`"
        )

        if len(result) > 4096:
            txt = wd/"links.txt"
            txt.write_text(f"Master: {master_url}\n\n"
                          + "\n".join(f"{k}: {v}" for k,v in q_urls.items())
                          + f"\n\nPlayer Format:\n{player_fmt}")
            await st.edit_text("✅ Done! Links file mein hain 👇")
            await m.reply_document(str(txt), caption="📋 HLS Links")
        else:
            await st.edit_text(result)

    except asyncio.CancelledError:
        await st.edit_text("⛔ Cancel ho gayi.")
    except Exception as e:
        await st.edit_text(f"❌ Error:\n`{str(e)[:300]}`")
        import traceback; traceback.print_exc()
    finally:
        jobs.pop(uid, None)
        shutil.rmtree(wd, ignore_errors=True)

if __name__ == "__main__":
    print("🎌 Kenshin Converter Bot")
    print(f"B2: {'✅' if HAS_B2 and B2_KEY_ID else '❌ Not configured'}")
    print(f"Admins: {ADMIN_IDS or 'All users'}")
    bot.run()
