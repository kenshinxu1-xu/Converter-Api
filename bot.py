"""
KENSHIN ANIME Telegram Bot - FIXED v3
- Caption: NO REPEAT BUG - generates once correctly
- Thumbnails: Proper Pillow-generated images
"""

import os, io, requests, logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")
JIKAN         = "https://api.jikan.moe/v4"
MANGADEX      = "https://api.mangadex.org"

# ───── API ─────
def jikan_anime(q, limit=6):
    try:
        r = requests.get(f"{JIKAN}/anime", params={"q": q, "limit": limit, "sfw": "true"}, timeout=10)
        return r.json().get("data", [])
    except: return []

def jikan_manga(q, limit=5, mtype=""):
    try:
        p = {"q": q, "limit": limit}
        if mtype: p["type"] = mtype
        r = requests.get(f"{JIKAN}/manga", params=p, timeout=10)
        return r.json().get("data", [])
    except: return []

def jikan_full(mal_id):
    try:
        r = requests.get(f"{JIKAN}/anime/{mal_id}/full", timeout=10)
        return r.json().get("data", {})
    except: return {}

def jikan_pics(mal_id):
    try:
        r = requests.get(f"{JIKAN}/anime/{mal_id}/pictures", timeout=10)
        return [p["jpg"].get("large_image_url", "") for p in r.json().get("data", []) if p.get("jpg")]
    except: return []

def dex_search(q, limit=5, lang=""):
    try:
        p = {"title": q, "limit": limit, "includes[]": "cover_art", "contentRating[]": ["safe", "suggestive"]}
        if lang: p["originalLanguage[]"] = lang
        r = requests.get(f"{MANGADEX}/manga", params=p, timeout=10)
        out = []
        for m in r.json().get("data", []):
            cov = next((x for x in m["relationships"] if x["type"] == "cover_art"), None)
            img = ""
            if cov and cov.get("attributes", {}).get("fileName"):
                img = "https://uploads.mangadex.org/covers/{}/{}.512.jpg".format(
                    m["id"], cov["attributes"]["fileName"])
            t = m["attributes"]["title"]
            title = t.get("en") or next(iter(t.values()), "Unknown")
            l = m["attributes"].get("originalLanguage", "")
            src = "manhwa" if l == "ko" else ("manhua" if l == "zh" else "manga")
            out.append({"id": m["id"], "title": title, "image": img, "source": src})
        return out
    except: return []

def load_img(url, size=None):
    if not url: return None
    proxy = "https://images.weserv.nl/?url={}&output=jpg&maxage=1d&n=-1".format(
        requests.utils.quote(url))
    for u in [proxy, url]:
        try:
            r = requests.get(u, timeout=12, headers={"User-Agent": "KenshinBot/3"})
            if r.status_code == 200:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                if size: img = img.resize(size, Image.LANCZOS)
                return img
        except: continue
    return None

# ───── CAPTION (FIXED - no loop, no repeat) ─────
def build_caption(a):
    title  = a.get("title_english") or a.get("title") or "Unknown"
    status = a.get("status") or "N/A"
    eps    = a.get("episodes") or "?"
    genres = ", ".join(g["name"] for g in a.get("genres", [])) or "N/A"
    syn    = (a.get("synopsis") or "No synopsis.")[:500]

    line = "\u2501" * 19
    star = "\u2B52"

    cap = (
        "\u2728 {} \u2728\n"
        "{}{}\n"
        "\u25A0 S\u1D07\u1D00s\u1D0F\u0274: 01\n"
        "\u25A0 Status: {}\n"
        "\u25A0 E\u1D18\u026As\u1D0F\u1D05\u1D07s: {}\n"
        "\u25A0 A\u1D1C\u1D05\u026A\u1D0F: [Hindi] #Official\n"
        "\u25A0 Q\u1D1C\u1D00\u029F\u026A\u1D1B\u028F: 480\u1D18 \u2022 720\u1D18 \u2022 1080\u1D18\n"
        "\u25A0 G\u1D07\u0274\u0280\u1D07s: {}\n"
        "{}{}\n"
        "\u2023 Synopsis : {}\n\n"
        "POWERED BY: [@KENSHIN_ANIME]"
    ).format(title, line, star, status, eps, genres, line, star, syn)

    return cap

async def ai_caption(a):
    if not ANTHROPIC_KEY:
        return build_caption(a)
    raw_syn = (a.get("synopsis") or "")[:600]
    title   = a.get("title_english") or a.get("title") or "Unknown"
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json",
                     "x-api-key": ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 180,
                  "messages": [{"role": "user", "content":
                      "Summarize this anime synopsis in 2-3 short sentences for Telegram. "
                      "Anime: {}\n\n{}\n\nWrite ONLY the summary, nothing else.".format(title, raw_syn)}]},
            timeout=15
        )
        improved = r.json()["content"][0]["text"].strip()
    except:
        improved = raw_syn[:400]

    status = a.get("status") or "N/A"
    eps    = a.get("episodes") or "?"
    genres = ", ".join(g["name"] for g in a.get("genres", [])) or "N/A"
    line   = "\u2501" * 19
    star   = "\u2B52"

    return (
        "\u2728 {} \u2728\n"
        "{}{}\n"
        "\u25A0 S\u1D07\u1D00s\u1D0F\u0274: 01\n"
        "\u25A0 Status: {}\n"
        "\u25A0 E\u1D18\u026As\u1D0F\u1D05\u1D07s: {}\n"
        "\u25A0 A\u1D1C\u1D05\u026A\u1D0F: [Hindi] #Official\n"
        "\u25A0 Q\u1D1C\u1D00\u029F\u026A\u1D1B\u028F: 480\u1D18 \u2022 720\u1D18 \u2022 1080\u1D18\n"
        "\u25A0 G\u1D07\u0274\u0280\u1D07s: {}\n"
        "{}{}\n"
        "\u2023 Synopsis : {}\n\n"
        "POWERED BY: [@KENSHIN_ANIME]"
    ).format(title, line, star, status, eps, genres, line, star, improved)

# ───── FONTS ─────
def fnt(sz, bold=True):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, sz)
            except: pass
    return ImageFont.load_default()

def wrap_text(text, font, max_w, draw):
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        try: tw = draw.textlength(test, font=font)
        except: tw = len(test) * (font.size // 2)
        if tw <= max_w: cur = test
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def shadow(draw, xy, text, font, fill, off=2):
    x, y = xy
    draw.text((x+off, y+off), text, font=font, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=font, fill=fill)

def paste_r(base, img, pos, r=12):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w-1, h-1], radius=r, fill=255)
    if img.mode != "RGBA": img = img.convert("RGBA")
    base.paste(img, pos, mask)

def done(canvas):
    out = Image.new("RGB", (1280, 720), (6, 3, 14))
    if canvas.mode == "RGBA": out.paste(canvas, mask=canvas.split()[3])
    else: out.paste(canvas)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=92, optimize=True)
    buf.seek(0)
    return buf

# ───── THUMBNAILS ─────
W, H = 1280, 720

def make_weebs(a):
    c = Image.new("RGBA", (W, H), (6, 3, 14, 255))
    title  = a.get("title_english") or a.get("title") or "?"
    genres = [g["name"] for g in a.get("genres", [])][:3]
    syn    = (a.get("synopsis") or "")[:190]
    eps    = str(a.get("episodes") or "?")
    p_url  = a.get("images", {}).get("jpg", {}).get("large_image_url", "")
    pics   = jikan_pics(a.get("mal_id", ""))
    bg_url = pics[1] if len(pics) > 1 else (pics[0] if pics else p_url)
    bg     = load_img(bg_url, (W, H))
    poster = load_img(p_url, (155, 220))
    d = ImageDraw.Draw(c)
    if bg:
        bb = bg.filter(ImageFilter.GaussianBlur(20))
        dk = Image.new("RGBA", (W, H), (2, 0, 8, 215))
        c.paste(Image.alpha_composite(bb.convert("RGBA"), dk), (0, 0))
        rx = 370
        rp = bg.resize((W - rx, H), Image.LANCZOS)
        gr = Image.new("RGBA", (W - rx, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(gr)
        for x in range(min(210, W - rx)):
            gd.line([(x, 0), (x, H)], fill=(2, 0, 8, int(255*(1-x/210))))
        rp2 = Image.alpha_composite(rp.convert("RGBA"), gr)
        c.paste(rp2, (rx, 0), rp2.split()[3])
    d = ImageDraw.Draw(c)
    PAD = 36
    d.rectangle([PAD, PAD, PAD+240, PAD+38], fill=(220, 40, 40, 240))
    d.text((PAD+12, PAD+8), "KENSHIN ANIME", font=fnt(18), fill="white")
    for i, (tab, col) in enumerate([("Anime", "white"), ("Season", (140, 140, 140)), ("Episodes", (140, 140, 140))]):
        tx = PAD + 260 + i * 90
        d.text((tx, PAD+10), tab, font=fnt(13, False), fill=col)
        if i == 0: d.line([(tx, PAD+32), (tx+55, PAD+32)], fill=(220, 40, 40), width=2)
    sz = min(58, max(28, int(360 / max(len(title), 8) * 1.5)))
    shadow(d, (PAD, PAD+54), title.upper()[:32], fnt(sz), "white")
    by = PAD + 54 + sz + 12
    d.rounded_rectangle([PAD, by, PAD+215, by+40], radius=6, fill=(255, 255, 255, 255))
    d.text((PAD+16, by+10), "\u25b6  DOWNLOAD NOW", font=fnt(15), fill=(6, 2, 12))
    py = by + 56
    if poster: paste_r(c, poster.convert("RGBA"), (PAD, py), r=8)
    mx = PAD + (poster.width if poster else 0) + 18
    d.text((mx, py), "SELECTED ANIME", font=fnt(11, False), fill=(150, 150, 150))
    d.text((mx, py+18), title[:26], font=fnt(16), fill="white")
    d.text((mx, py+40), "Eps: {}".format(eps), font=fnt(13, False), fill=(120, 120, 120))
    sy = py + (poster.height if poster else 0) + 14
    for ln in wrap_text(syn, fnt(13, False), 340, d)[:4]:
        d.text((PAD, sy), ln, font=fnt(13, False), fill=(170, 170, 170)); sy += 20
    gx = PAD; gy = sy + 6
    for g in genres:
        try: gw = int(d.textlength(g, font=fnt(13)) + 22)
        except: gw = len(g) * 9 + 22
        d.rounded_rectangle([gx, gy, gx+gw, gy+26], radius=13, fill=(255,255,255,15), outline=(180,180,180,110), width=1)
        d.text((gx+11, gy+6), g, font=fnt(13), fill="white"); gx += gw + 10
    d.text((PAD+50, H-28), "EXPAND TO SEE MORE", font=fnt(11, False), fill=(70, 70, 70))
    return done(c)

def make_kenshin(a):
    c = Image.new("RGBA", (W, H), (14, 6, 8, 255))
    title  = a.get("title_english") or a.get("title") or "?"
    score  = str(a.get("score") or "N/A")
    eps    = str(a.get("episodes") or "?")
    p_url  = a.get("images", {}).get("jpg", {}).get("large_image_url", "")
    pics   = jikan_pics(a.get("mal_id", ""))
    ch_url = pics[0] if pics else p_url
    poster = load_img(p_url, (305, 415))
    char   = load_img(ch_url, (205, 510))
    d = ImageDraw.Draw(c)
    if poster:
        bb = poster.resize((W, H)).filter(ImageFilter.GaussianBlur(45))
        dk = Image.new("RGBA", (W, H), (8, 3, 5, 215))
        c.paste(Image.alpha_composite(bb.convert("RGBA"), dk), (0, 0))
    d = ImageDraw.Draw(c)
    px, py, pw, ph, pr = 26, 35, 205, 510, 22
    d.rounded_rectangle([px, py, px+pw, py+ph], radius=pr, fill=(10,4,5,230), outline=(255,255,255,28), width=2)
    if char:
        mask = Image.new("L", (pw, ph), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw-1, ph-1], radius=pr, fill=255)
        c.paste(char, (px, py), mask)
        fi = Image.new("RGBA", (pw, 150), (0, 0, 0, 0))
        for i in range(150):
            ImageDraw.Draw(fi).line([(0, 149-i), (pw, 149-i)], fill=(8, 3, 5, int(200*i/150)))
        c.paste(fi, (px, py+ph-150), fi.split()[3])
    d.rounded_rectangle([px+65, py+7, px+140, py+17], radius=5, fill=(0, 0, 0, 180))
    cx = px + pw + 22
    shadow(d, (cx, 30), title.upper()[:30], fnt(32), "white")
    d.text((cx, 74), "KENSHIN ANIME", font=fnt(18), fill=(255, 204, 0))
    if poster: paste_r(c, poster.convert("RGBA"), (cx, 100), r=12)
    by = H - 60; bx = cx
    for lbl in ["WATCH NOW", "KENSHIN ANIME"]:
        bw = 148
        d.rounded_rectangle([bx, by, bx+bw, by+42], radius=8, fill=(10,6,8,240), outline=(255,255,255,38), width=1)
        try: lw = d.textlength(lbl, font=fnt(13))
        except: lw = len(lbl)*7
        d.text((bx+(bw-lw)//2, by+13), lbl, font=fnt(13), fill="white")
        bx += bw + 10
    c2, cy2, r = W-155, H//2, 108
    d.ellipse([c2-r, cy2-r, c2+r, cy2+r], fill=(0,3,20,200), outline=(30,111,255,145), width=3)
    for ri in [r-16, r-30]:
        d.ellipse([c2-ri, cy2-ri, c2+ri, cy2+ri], outline=(30,111,255,50), width=1)
    d.line([(c2, cy2-r+6), (c2, cy2+r-6)], fill=(77,168,255,38), width=1)
    d.line([(c2-r+6, cy2), (c2+r-6, cy2)], fill=(77,168,255,38), width=1)
    short = title.split(":")[0][:12].upper()
    try: sw = d.textlength(short, font=fnt(14))
    except: sw = len(short)*8
    d.text((c2-sw//2, cy2-10), short, font=fnt(14), fill=(120,185,255,215))
    return done(c)

def make_campus(a):
    c = Image.new("RGBA", (W, H), (3, 1, 10, 255))
    title  = a.get("title_english") or a.get("title") or "?"
    genres = [g["name"] for g in a.get("genres", [])][:3]
    syn    = (a.get("synopsis") or "")[:260]
    score  = a.get("score") or "N/A"
    eps    = str(a.get("episodes") or "?")
    p_url  = a.get("images", {}).get("jpg", {}).get("large_image_url", "")
    pics   = jikan_pics(a.get("mal_id", ""))
    bg_url = pics[1] if len(pics) > 1 else (pics[0] if pics else p_url)
    bg     = load_img(bg_url, (W, H))
    poster = load_img(p_url, (230, 325))
    if bg:
        bb = bg.filter(ImageFilter.GaussianBlur(22))
        dk = Image.new("RGBA", (W, H), (3, 1, 10, 205))
        c.paste(Image.alpha_composite(bb.convert("RGBA"), dk), (0, 0))
    d = ImageDraw.Draw(c)
    d.rectangle([0, 0, W, 50], fill=(0, 0, 0, 200))
    d.rectangle([0, 0, 4, 50], fill=(220, 40, 40))
    d.text((16, 14), "KENSHIN ANIME", font=fnt(18), fill="white")
    d.line([(16, 48), (16+155, 48)], fill=(220, 40, 40), width=2)
    for i, (tab, col) in enumerate([("Anime", "white"), ("Season", (120,120,120)), ("Episodes", (120,120,120))]):
        d.text((W-340+i*112, 16), tab, font=fnt(14, False), fill=col)
    if poster: paste_r(c, poster.convert("RGBA"), (28, 65), r=10)
    ix = 275
    d.text((ix, 68), "TITLE", font=fnt(12, False), fill=(130,130,130))
    sz = 42 if len(title) <= 18 else (32 if len(title) <= 28 else 24)
    shadow(d, (ix, 88), title, fnt(sz), "white")
    ty = 88 + sz + 10
    d.text((ix, ty), ", ".join(genres), font=fnt(15, False), fill=(175,175,175)); ty += 30
    try: stars = min(5, round(float(score)/10*5))
    except: stars = 4
    sx = ix
    for i in range(5):
        d.text((sx, ty), "\u2605" if i < stars else "\u2606", font=fnt(24),
               fill=(255,149,0) if i < stars else (65,65,65)); sx += 28
    d.text((sx+8, ty+2), str(score), font=fnt(24), fill="white"); ty += 38
    for ln in wrap_text(syn, fnt(14, False), W-ix-40, d)[:5]:
        d.text((ix, ty), ln, font=fnt(14, False), fill=(165,165,165)); ty += 22
    ty += 10
    d.rounded_rectangle([ix, ty, ix+128, ty+44], radius=8, fill=(220,40,40))
    d.text((ix+30, ty+13), "READ", font=fnt(16), fill="white")
    d.rounded_rectangle([ix+140, ty, ix+285, ty+44], radius=8, outline=(175,175,175,140), width=1)
    d.text((ix+168, ty+13), "MY LIST", font=fnt(16), fill="white")
    ty += 58; gx = ix
    for g in genres:
        try: gw = int(d.textlength(g, font=fnt(13)) + 22)
        except: gw = len(g)*9 + 22
        d.rounded_rectangle([gx, ty, gx+gw, ty+26], radius=13, outline=(190,190,190,95), width=1)
        d.text((gx+11, ty+6), g, font=fnt(13), fill="white"); gx += gw + 10
    return done(c)

def make_thumb(a, style="weebs"):
    return {"weebs": make_weebs, "kenshin": make_kenshin, "campus": make_campus}.get(style, make_weebs)(a)

# ───── HANDLERS ─────
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "KENSHIN ANIME Bot\n\n"
        "Commands:\n"
        "/anime <name> - Search anime\n"
        "/manga <name> - Search manga\n"
        "/manhwa <name> - Search manhwa\n"
        "/manhua <name> - Search manhua\n"
        "/caption <name> - Get Telegram caption\n"
        "/thumb <name> - Weebs thumbnail\n"
        "/thumb2 <name> - Kenshin thumbnail\n"
        "/thumb3 <name> - Campus thumbnail\n"
        "/info <name> - Full anime info\n"
        "/top - Top airing anime\n"
        "/upcoming - Upcoming anime\n\n"
        "Or just type any anime name!"
    )

async def cmd_help(u, ctx): await cmd_start(u, ctx)

async def cmd_anime(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /anime Solo Leveling"); return
    msg = await u.message.reply_text("Searching: {}...".format(q))
    res = jikan_anime(q)
    if not res: await msg.edit_text("No anime found."); return
    btns = [[InlineKeyboardButton(
        "{} {}{}".format(
            "🎬", (r.get("title_english") or r.get("title", "?"))[:36],
            " ⭐{}".format(r["score"]) if r.get("score") else ""
        ), callback_data="a:{}".format(r["mal_id"])
    )] for r in res[:6]]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text("Results for {}:".format(q), reply_markup=InlineKeyboardMarkup(btns))

async def cmd_manga(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /manga Berserk"); return
    msg = await u.message.reply_text("Searching manga: {}...".format(q))
    res = jikan_manga(q, mtype="manga")
    if not res: await msg.edit_text("Not found."); return
    btns = [[InlineKeyboardButton(
        "📖 {}".format((r.get("title_english") or r.get("title", "?"))[:36]),
        callback_data="manga:j:{}".format(r["mal_id"])
    )] for r in res[:5]]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text("Manga results:", reply_markup=InlineKeyboardMarkup(btns))

async def cmd_manhwa(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /manhwa Solo Leveling"); return
    msg = await u.message.reply_text("Searching manhwa: {}...".format(q))
    res = dex_search(q, lang="ko") or jikan_manga(q, mtype="manhwa")
    if not res: await msg.edit_text("Not found."); return
    btns = [[InlineKeyboardButton(
        "🇰🇷 {}".format(r.get("title", r.get("title_english", "?"))[:36]),
        callback_data="manga:dex:{}".format(r.get("id", r.get("mal_id", "")))
    )] for r in res[:5]]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text("Manhwa results:", reply_markup=InlineKeyboardMarkup(btns))

async def cmd_manhua(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /manhua Battle Through Heavens"); return
    msg = await u.message.reply_text("Searching manhua: {}...".format(q))
    res = dex_search(q, lang="zh") or jikan_manga(q, mtype="manhua")
    if not res: await msg.edit_text("Not found."); return
    btns = [[InlineKeyboardButton(
        "🇨🇳 {}".format(r.get("title", r.get("title_english", "?"))[:36]),
        callback_data="manga:dex:{}".format(r.get("id", r.get("mal_id", "")))
    )] for r in res[:5]]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text("Manhua results:", reply_markup=InlineKeyboardMarkup(btns))

async def cmd_caption(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /caption Solo Leveling"); return
    msg = await u.message.reply_text("Generating caption for {}...".format(q))
    res = jikan_anime(q, limit=1)
    if not res: await msg.edit_text("Anime not found."); return
    cap = await ai_caption(res[0])
    img = load_img(res[0].get("images", {}).get("jpg", {}).get("large_image_url", ""))
    sent = False
    if img:
        buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=90); buf.seek(0)
        try:
            await ctx.bot.send_photo(chat_id=u.effective_chat.id, photo=buf, caption=cap[:1024])
            await msg.delete(); sent = True
        except Exception as e: logger.error(e)
    if not sent:
        await msg.edit_text(cap[:4096])

async def _do_thumb(u, ctx, q, style):
    names = {"weebs": "Weebs", "kenshin": "Kenshin", "campus": "Campus"}
    msg = await u.message.reply_text("Generating {} thumbnail for {}...".format(names[style], q))
    res = jikan_anime(q, limit=1)
    if not res: await msg.edit_text("Not found."); return
    a = jikan_full(res[0]["mal_id"]) or res[0]
    try:
        buf = make_thumb(a, style)
        cap = build_caption(a)[:1024]
        await ctx.bot.send_photo(chat_id=u.effective_chat.id, photo=buf, caption=cap)
        await msg.delete()
    except Exception as e:
        logger.error("thumb error: {}".format(e), exc_info=True)
        await msg.edit_text("Thumbnail error: {}".format(str(e)[:100]))

async def cmd_thumb(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /thumb Solo Leveling"); return
    await _do_thumb(u, ctx, q, "weebs")

async def cmd_thumb2(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /thumb2 Solo Leveling"); return
    await _do_thumb(u, ctx, q, "kenshin")

async def cmd_thumb3(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /thumb3 Solo Leveling"); return
    await _do_thumb(u, ctx, q, "campus")

async def cmd_info(u: Update, ctx):
    q = " ".join(ctx.args).strip()
    if not q: await u.message.reply_text("Usage: /info Demon Slayer"); return
    msg = await u.message.reply_text("Fetching info for {}...".format(q))
    res = jikan_anime(q, limit=1)
    if not res: await msg.edit_text("Not found."); return
    a = jikan_full(res[0]["mal_id"]) or res[0]
    title   = a.get("title_english") or a.get("title") or "?"
    genres  = ", ".join(g["name"] for g in a.get("genres", []))
    studios = ", ".join(s["name"] for s in a.get("studios", [])) or "N/A"
    syn     = (a.get("synopsis") or "")[:350]
    text = ("{}\n\nType: {} | Episodes: {}\nScore: {} | Rank: #{}\n"
            "Year: {} | {}\nGenres: {}\nStudio: {}\n\n{}").format(
        title, a.get("type","?"), a.get("episodes","?"),
        a.get("score","?"), a.get("rank","?"),
        a.get("year","?"), a.get("status","?"),
        genres, studios, syn)
    img = load_img(a.get("images", {}).get("jpg", {}).get("large_image_url", ""))
    sent = False
    if img:
        buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=90); buf.seek(0)
        try:
            await ctx.bot.send_photo(chat_id=u.effective_chat.id, photo=buf, caption=text[:1024])
            await msg.delete(); sent = True
        except Exception as e: logger.error(e)
    if not sent: await msg.edit_text(text[:4096])

async def cmd_top(u: Update, ctx):
    msg = await u.message.reply_text("Fetching top airing anime...")
    try:
        r = requests.get(f"{JIKAN}/top/anime", params={"filter":"airing","limit":10}, timeout=10)
        data = r.json().get("data", [])
        lines = ["Top Airing Anime:\n"]
        for i, a in enumerate(data, 1):
            t = a.get("title_english") or a.get("title") or "?"
            lines.append("{}. {} - {}".format(i, t, a.get("score","N/A")))
        await msg.edit_text("\n".join(lines))
    except Exception as e: await msg.edit_text("Error: {}".format(str(e)[:100]))

async def cmd_upcoming(u: Update, ctx):
    msg = await u.message.reply_text("Fetching upcoming anime...")
    try:
        r = requests.get(f"{JIKAN}/top/anime", params={"filter":"upcoming","limit":8}, timeout=10)
        data = r.json().get("data", [])
        lines = ["Upcoming Anime:\n"]
        for i, a in enumerate(data, 1):
            t = a.get("title_english") or a.get("title") or "?"
            lines.append("{}. {} - {}".format(i, t, a.get("year","TBA")))
        await msg.edit_text("\n".join(lines))
    except Exception as e: await msg.edit_text("Error: {}".format(str(e)[:100]))

async def btn_handler(u: Update, ctx):
    q = u.callback_query
    await q.answer()
    data = q.data

    if data == "cancel":
        try: await q.message.delete()
        except: pass
        return

    if data.startswith("a:"):
        mal_id = int(data[2:])
        await q.message.edit_text("Loading...")
        a = jikan_full(mal_id)
        if not a: await q.message.edit_text("Error."); return
        title  = a.get("title_english") or a.get("title") or "?"
        genres = ", ".join(g["name"] for g in a.get("genres", []))
        syn    = (a.get("synopsis") or "")[:220]
        text   = "{}\n{} | {} eps | {}\n{}\n\n{}...".format(
            title, a.get("type","?"), a.get("episodes","?"), a.get("score","?"), genres, syn)
        btns = [
            [InlineKeyboardButton("Caption", callback_data="cap:{}".format(mal_id)),
             InlineKeyboardButton("Weebs Thumb", callback_data="th:weebs:{}".format(mal_id))],
            [InlineKeyboardButton("Kenshin Thumb", callback_data="th:kenshin:{}".format(mal_id)),
             InlineKeyboardButton("Campus Thumb", callback_data="th:campus:{}".format(mal_id))],
            [InlineKeyboardButton("Back", callback_data="cancel")]
        ]
        img = load_img(a.get("images", {}).get("jpg", {}).get("large_image_url", ""))
        sent = False
        if img:
            buf = io.BytesIO(); img.convert("RGB").save(buf, "JPEG", quality=90); buf.seek(0)
            try:
                await ctx.bot.send_photo(chat_id=q.message.chat.id, photo=buf,
                    caption=text[:1024], reply_markup=InlineKeyboardMarkup(btns))
                await q.message.delete(); sent = True
            except Exception as e: logger.error(e)
        if not sent:
            await q.message.edit_text(text[:1024], reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("cap:"):
        mal_id = int(data[4:])
        await q.message.edit_text("Generating caption...")
        a = jikan_full(mal_id)
        if not a: await q.message.edit_text("Error."); return
        cap = await ai_caption(a)
        await q.message.edit_text(cap[:4096])

    elif data.startswith("th:"):
        parts  = data.split(":")
        style  = parts[1]
        mal_id = int(parts[2])
        await q.message.edit_text("Generating {} thumbnail...".format(style))
        a = jikan_full(mal_id)
        if not a: await q.message.edit_text("Error."); return
        try:
            buf = make_thumb(a, style)
            cap = build_caption(a)[:1024]
            await ctx.bot.send_photo(chat_id=q.message.chat.id, photo=buf, caption=cap)
            await q.message.delete()
        except Exception as e:
            logger.error("thumb callback: {}".format(e), exc_info=True)
            await q.message.edit_text("Thumbnail error: {}".format(str(e)[:100]))

    elif data.startswith("manga:"):
        mid = data[6:]
        await q.message.edit_text("Item: {}\nUse /caption or /thumb for more details.".format(mid))

async def text_handler(u: Update, ctx):
    q = u.message.text.strip()
    if len(q) < 2 or q.startswith("/"): return
    res = jikan_anime(q, limit=5)
    if not res:
        await u.message.reply_text("No anime found for '{}'. Try /manhwa or /manga.".format(q))
        return
    msg = await u.message.reply_text("Searching: {}...".format(q))
    btns = [[InlineKeyboardButton(
        "🎬 {}".format((r.get("title_english") or r.get("title","?"))[:36]),
        callback_data="a:{}".format(r["mal_id"])
    )] for r in res[:5]]
    btns.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text("Results for {}:".format(q), reply_markup=InlineKeyboardMarkup(btns))

# ───── MAIN ─────
def main():
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Set BOT_TOKEN environment variable!"); return
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    for cmd, fn in [
        ("start", cmd_start), ("help", cmd_help), ("anime", cmd_anime),
        ("manga", cmd_manga), ("manhwa", cmd_manhwa), ("manhua", cmd_manhua),
        ("caption", cmd_caption), ("thumb", cmd_thumb), ("thumb2", cmd_thumb2),
        ("thumb3", cmd_thumb3), ("info", cmd_info), ("top", cmd_top),
        ("upcoming", cmd_upcoming)
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    app.add_handler(CallbackQueryHandler(btn_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("KENSHIN ANIME Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
