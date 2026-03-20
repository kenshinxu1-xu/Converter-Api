"""
KENSHIN ANIME Telegram Bot
Complete bot with anime/manga search, captions, thumbnails
Deploy on Railway: https://railway.app
"""

import os, io, asyncio, requests, logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY", "")   # optional for AI captions
JIKAN         = "https://api.jikan.moe/v4"
MANGADEX      = "https://api.mangadex.org"

# ─── FONT SETUP ───────────────────────────────────────
def get_font(size=20, bold=False):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/system/fonts/Roboto-Bold.ttf",
    ]
    if not bold:
        font_paths = [p.replace("Bold","Regular").replace("-Bold","") for p in font_paths] + font_paths
    for fp in font_paths:
        if os.path.exists(fp):
            try: return ImageFont.truetype(fp, size)
            except: pass
    return ImageFont.load_default()

# ─── HELPERS ──────────────────────────────────────────
def jikan_search_anime(query, limit=5):
    try:
        r = requests.get(f"{JIKAN}/anime", params={"q": query, "limit": limit, "sfw": "true"}, timeout=10)
        return r.json().get("data", [])
    except: return []

def jikan_search_manga(query, limit=5, type_filter=""):
    try:
        params = {"q": query, "limit": limit}
        if type_filter: params["type"] = type_filter
        r = requests.get(f"{JIKAN}/manga", params=params, timeout=10)
        return r.json().get("data", [])
    except: return []

def mangadex_search(query, limit=5, lang=""):
    try:
        params = {"title": query, "limit": limit, "includes[]": "cover_art",
                  "contentRating[]": ["safe","suggestive"]}
        if lang: params["originalLanguage[]"] = lang
        r = requests.get(f"{MANGADEX}/manga", params=params, timeout=10)
        data = r.json().get("data", [])
        results = []
        for m in data:
            cov = next((rel for rel in m["relationships"] if rel["type"]=="cover_art"), None)
            img = ""
            if cov and cov.get("attributes",{}).get("fileName"):
                img = f"https://uploads.mangadex.org/covers/{m['id']}/{cov['attributes']['fileName']}.512.jpg"
            t = m["attributes"]["title"]
            title = t.get("en") or t.get("ja-ro") or next(iter(t.values()), "Unknown")
            results.append({"id": m["id"], "title": title, "image": img,
                           "status": m["attributes"].get("status",""),
                           "lang": m["attributes"].get("originalLanguage",""),
                           "tags": [tg["attributes"]["name"].get("en","") for tg in m["attributes"].get("tags",[]) if tg["attributes"].get("group")=="genre"]})
        return results
    except: return []

def get_anime_full(mal_id):
    try:
        r = requests.get(f"{JIKAN}/anime/{mal_id}/full", timeout=10)
        return r.json().get("data", {})
    except: return {}

def get_anime_pics(mal_id):
    try:
        r = requests.get(f"{JIKAN}/anime/{mal_id}/pictures", timeout=10)
        pics = r.json().get("data", [])
        return [p["jpg"].get("large_image_url","") for p in pics if p.get("jpg")]
    except: return []

def load_image_from_url(url, size=None):
    """Load image from URL, return PIL Image or None"""
    if not url: return None
    try:
        proxy = f"https://images.weserv.nl/?url={requests.utils.quote(url)}&output=jpg&maxage=1d"
        r = requests.get(proxy, timeout=10, headers={"User-Agent": "KenshinBot/1.0"})
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        if size: img = img.resize(size, Image.LANCZOS)
        return img
    except:
        try:
            r2 = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            img = Image.open(io.BytesIO(r2.content)).convert("RGBA")
            if size: img = img.resize(size, Image.LANCZOS)
            return img
        except: return None

def make_caption(anime):
    """Generate formatted Telegram caption"""
    title = anime.get("title_english") or anime.get("title","Unknown")
    status = anime.get("status","N/A")
    eps = anime.get("episodes","?") or "?"
    genres = ", ".join([g["name"] for g in anime.get("genres",[])])
    syn = (anime.get("synopsis","") or "")[:500]
    return (
        f"\u2728 {title} \u2728\n"
        f"\u2501"*19 + "\u2b52\n"
        f"\u25a0 S\u1d07\u1d00s\u1d0f\u0274: 01\n"
        f"\u25a0 Status: {status}\n"
        f"\u25a0 E\u1d18\u026as\u1d0f\u1d05\u1d07s: {eps}\n"
        f"\u25a0 A\u1d1c\u1d05\u026a\u1d0f: [Hindi] #Official\n"
        f"\u25a0 Q\u1d1c\u1d00\u029f\u026a\u1d1b\u028f: 480\u1d18 \u2022 720\u1d18 \u2022 1080\u1d18\n"
        f"\u25a0 G\u1d07\u0274\u0280\u1d07s: {genres}\n"
        f"\u2501"*19 + "\u2b52\n"
        f"\u2023 Synopsis : {syn}\n\n"
        f"POWERED BY: [@KENSHIN_ANIME]"
    )

async def ai_caption(anime):
    """Generate caption using Claude AI (if key available)"""
    if not ANTHROPIC_KEY:
        return make_caption(anime)
    title = anime.get("title_english") or anime.get("title","Unknown")
    genres = ", ".join([g["name"] for g in anime.get("genres",[])])
    eps = anime.get("episodes","?") or "?"
    status = anime.get("status","N/A")
    syn = (anime.get("synopsis","") or "")[:400]
    tmpl = make_caption(anime)
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type":"application/json","x-api-key":ANTHROPIC_KEY,"anthropic-version":"2023-06-01"},
            json={"model":"claude-sonnet-4-20250514","max_tokens":900,
                  "messages":[{"role":"user","content":f"Create a Telegram caption for Hindi anime channel KENSHIN_ANIME for anime '{title}'. Use EXACTLY this format filled: {tmpl}\nReturn ONLY the caption text."}]},
            timeout=20
        )
        return r.json()["content"][0]["text"].strip()
    except:
        return tmpl

# ─── THUMBNAIL GENERATOR ──────────────────────────────
def make_thumbnail(anime, style="weebs"):
    """Generate 1280x720 thumbnail using Pillow"""
    W, H = 1280, 720
    img = Image.new("RGBA", (W, H), (6, 3, 14, 255))
    draw = ImageDraw.Draw(img)

    title = (anime.get("title_english") or anime.get("title","Unknown"))[:40]
    score = str(anime.get("score","N/A"))
    eps   = str(anime.get("episodes","?") or "?")
    genres = [g["name"] for g in anime.get("genres",[])][:3]
    poster_url = anime.get("images",{}).get("jpg",{}).get("large_image_url","")

    # Load poster/background
    pics = get_anime_pics(anime.get("mal_id",""))
    bg_url = pics[1] if len(pics)>1 else (pics[0] if pics else poster_url)
    bg = load_image_from_url(bg_url, (W, H))
    poster = load_image_from_url(poster_url, (200, 280))

    if style == "kenshin":
        _draw_kenshin_style(img, draw, bg, poster, title, score, eps, genres)
    elif style == "campus":
        _draw_campus_style(img, draw, bg, poster, title, score, eps, genres, anime)
    else:
        _draw_weebs_style(img, draw, bg, poster, title, score, eps, genres, anime)

    # Convert to RGB for JPEG
    out = Image.new("RGB", (W, H), (6, 3, 14))
    out.paste(img, mask=img.split()[3] if img.mode=='RGBA' else None)
    buf = io.BytesIO()
    out.save(buf, "PNG", optimize=True)
    buf.seek(0)
    return buf

def _draw_weebs_style(img, draw, bg, poster, title, score, eps, genres, anime):
    W, H = 1280, 720
    # BG blur on right
    if bg:
        bg_right = bg.crop((0,0,W,H))
        bg_blur = bg_right.filter(ImageFilter.GaussianBlur(18))
        # Darken
        dark = Image.new("RGBA",(W,H),(2,0,8,200))
        bg_blur = Image.alpha_composite(bg_blur.convert("RGBA"), dark)
        img.paste(bg_blur, (0,0))
        # Sharp on right 65%
        right_x = int(W*0.35)
        right_img = bg.crop((0,0,W,H)).resize((W-right_x,H))
        # Gradient overlay
        grad = Image.new("RGBA",(W-right_x,H),(0,0,0,0))
        gd = ImageDraw.Draw(grad)
        for x in range(min(200, W-right_x)):
            alpha = int(220*(1-(x/200)))
            gd.line([(x,0),(x,H)], fill=(2,0,8,alpha))
        right_with_grad = Image.alpha_composite(right_img.convert("RGBA"), grad)
        img.paste(right_with_grad, (right_x, 0), right_with_grad.split()[3])

    draw = ImageDraw.Draw(img)
    # Left panel
    # Title
    f_title = get_font(72, bold=True)
    f_med   = get_font(22, bold=True)
    f_small = get_font(15)
    f_tiny  = get_font(12)
    pad = 40

    # KENSHIN ANIME label
    draw.rectangle([pad, pad, pad+220, pad+36], fill=(255,68,68,200))
    draw.text((pad+10, pad+8), "KENSHIN ANIME", font=get_font(16,True), fill="white")

    # Big title
    title_disp = title.upper()
    draw.text((pad, pad+60), title_disp, font=f_title, fill="white")

    # Download button
    bx, by = pad, pad+160
    draw.rectangle([bx, by, bx+220, by+42], fill="white", outline="white")
    draw.text((bx+14, by+10), "\u25b6 DOWNLOAD NOW", font=get_font(16,True), fill=(6,2,12))

    # Mini poster
    if poster:
        px, py = pad, by+60
        img.paste(poster.convert("RGBA"), (px, py), poster.convert("RGBA").split()[3])
        draw.text((px+poster.width+14, py), title[:30], font=f_med, fill="white")
        draw.text((px+poster.width+14, py+28), f"Eps: {eps}", font=f_small, fill=(180,180,180))

    # Genres
    gx = pad
    gy = by + 60 + (poster.height if poster else 0) + 14
    for g in genres:
        gw = get_font(14,True).getlength(g)+20
        draw.rounded_rectangle([gx, gy, gx+int(gw), gy+26], radius=13, outline=(200,200,200,160), width=1)
        draw.text((gx+10, gy+5), g, font=get_font(14,True), fill="white")
        gx += int(gw)+10

def _draw_kenshin_style(img, draw, bg, poster, title, score, eps, genres):
    W, H = 1280, 720
    if bg:
        bg_dark = bg.filter(ImageFilter.GaussianBlur(35))
        dark_ov = Image.new("RGBA",(W,H),(10,4,8,180))
        bg_dark = Image.alpha_composite(bg_dark.convert("RGBA"), dark_ov)
        img.paste(bg_dark,(0,0))

    draw = ImageDraw.Draw(img)
    # Red left stripe
    draw.rectangle([0,0,5,H], fill=(255,50,50,255))

    # Phone frame left - character placeholder (blue rect)
    px,py,pw,ph = 30,40,180,420
    draw.rounded_rectangle([px,py,px+pw,py+ph], radius=22, fill=(10,4,4,220), outline=(255,255,255,30), width=2)
    if bg:
        char_crop = bg.crop((0,0,200,400)).resize((pw,ph))
        char_mask = Image.new("L",(pw,ph),0)
        ImageDraw.Draw(char_mask).rounded_rectangle([0,0,pw-1,ph-1],radius=22,fill=255)
        img.paste(char_crop,(px,py),char_mask)

    # Center poster
    if poster:
        cx,cy = 240,80
        img.paste(poster.convert("RGBA"),(cx,cy),poster.convert("RGBA").split()[3])
        draw.rounded_rectangle([cx-2,cy-2,cx+poster.width+2,cy+poster.height+2],radius=10,outline=(255,255,255,30),width=2)

    # Right side text
    tx = 700
    draw.text((tx, 60), title.upper(), font=get_font(52,True), fill="white")
    draw.text((tx, 140), "KENSHIN ANIME", font=get_font(20,True), fill=(255,204,0))
    draw.line([(tx,170),(tx+350,170)], fill=(255,204,0,180), width=2)

    # Badges
    badges = [("SEASON 01","#ff5050"),("HINDI","#ffcc00"),(f"{eps} EPS","#7ab8ff"),("480p 720p 1080p","#b8a9ff")]
    bx2=tx; by2=190
    for b,c in badges:
        crgb = tuple(int(c.lstrip('#')[i:i+2],16) for i in (0,2,4))
        bw = int(get_font(14,True).getlength(b))+22
        draw.rounded_rectangle([bx2,by2,bx2+bw,by2+30],radius=6,fill=(*crgb,35),outline=(*crgb,120),width=1)
        draw.text((bx2+11,by2+7), b, font=get_font(14,True), fill=c)
        bx2 += bw+8

    # Score badge
    draw.rounded_rectangle([1150,40,1250,110],radius=10,fill=(0,0,0,180),outline=(255,204,0,200),width=2)
    draw.text((1165,48), score, font=get_font(42,True), fill=(255,204,0))
    draw.text((1175,96), "SCORE", font=get_font(11), fill=(255,204,0,160))

def _draw_campus_style(img, draw, bg, poster, title, score, eps, genres, anime):
    W, H = 1280, 720
    if bg:
        bg_blur = bg.filter(ImageFilter.GaussianBlur(20))
        dark = Image.new("RGBA",(W,H),(3,1,10,190))
        bg_blur = Image.alpha_composite(bg_blur.convert("RGBA"), dark)
        img.paste(bg_blur,(0,0))
    draw = ImageDraw.Draw(img)
    # Top bar - KENSHIN ANIME
    draw.rectangle([0,0,W,48],fill=(0,0,0,190))
    draw.text((20,12), "KENSHIN ANIME", font=get_font(18,True), fill="white")
    draw.line([(20,46),(120,46)], fill=(255,68,68,255), width=2)

    # Left poster
    if poster:
        img.paste(poster.convert("RGBA"),(20,60),poster.convert("RGBA").split()[3])

    # Right info
    ix = 240
    draw.text((ix,60),"TITLE",font=get_font(12),fill=(180,180,180))
    draw.text((ix,80), title, font=get_font(40,True), fill="white")
    draw.text((ix,130),", ".join(genres), font=get_font(16), fill=(200,200,200))
    # Stars
    stars = min(5,round(float(score or 0)/10*5))
    sx=ix; sy=162
    for i in range(5):
        draw.text((sx,sy),"\u2605" if i<stars else "\u2606",font=get_font(26,True),fill=(255,149,0) if i<stars else (80,80,80))
        sx+=30
    draw.text((sx+10,sy+2), score, font=get_font(26,True), fill="white")

    syn = (anime.get("synopsis","") or "")[:300]
    # Wrap text
    words=syn.split(); lines=[]; line=""
    for w in words:
        test=line+" "+w if line else w
        if get_font(14).getlength(test)>580: lines.append(line); line=w
        else: line=test
    if line: lines.append(line)
    ty=210
    for ln in lines[:6]:
        draw.text((ix,ty),ln,font=get_font(14),fill=(180,180,180)); ty+=20

    draw.rounded_rectangle([ix,ty+10,ix+100,ty+44],radius=8,fill=(220,50,50,255))
    draw.text((ix+16,ty+16),"READ",font=get_font(16,True),fill="white")
    draw.rounded_rectangle([ix+110,ty+10,ix+230,ty+44],radius=8,outline=(180,180,180,160),width=1)
    draw.text((ix+126,ty+16),"MY LIST",font=get_font(16,True),fill="white")

# ─── BOT HANDLERS ─────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🎌 *KENSHIN ANIME Bot*\n\n"
        "Official Hindi anime channel bot!\n\n"
        "*Commands:*\n"
        "🔍 /anime `<name>` — Search anime\n"
        "📚 /manga `<name>` — Search manga\n"
        "🇰🇷 /manhwa `<name>` — Search manhwa\n"
        "🇨🇳 /manhua `<name>` — Search manhua\n"
        "📝 /caption `<name>` — Get Telegram caption\n"
        "🖼 /thumbnail `<name>` — Get thumbnail\n"
        "🖼 /thumb2 `<name>` — Kenshin style thumb\n"
        "🖼 /thumb3 `<name>` — Campus style thumb\n"
        "📊 /info `<name>` — Full anime info\n"
        "🔥 /top — Top airing anime\n"
        "❓ /help — Show all commands\n\n"
        "Or just type any anime name!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

async def anime_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /anime Solo Leveling")
        return
    msg = await update.message.reply_text(f"🔍 Searching: {q}...")
    results = jikan_search_anime(q, limit=6)
    if not results:
        await msg.edit_text("❌ No results found.")
        return
    buttons = [[InlineKeyboardButton(
        f"{'🎬' if r.get('type')=='TV' else '📽'} {(r.get('title_english') or r.get('title','?'))[:40]}",
        callback_data=f"anime_{r['mal_id']}"
    )] for r in results[:6]]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text(f"🔍 Results for *{q}*:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def manga_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /manga Berserk")
        return
    await _search_manga(update, ctx, q, "manga")

async def manhwa_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /manhwa Solo Leveling")
        return
    await _search_manga(update, ctx, q, "manhwa")

async def manhua_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /manhua Battle Through Heavens")
        return
    await _search_manga(update, ctx, q, "manhua")

async def _search_manga(update, ctx, q, type_filter):
    msg = await update.message.reply_text(f"🔍 Searching {type_filter}: {q}...")
    lang_map = {"manhwa":"ko","manhua":"zh","manga":""}
    # Try MangaDex first for manhwa/manhua
    results = []
    if type_filter in ("manhwa","manhua"):
        results = mangadex_search(q, limit=5, lang=lang_map[type_filter])
    if not results:
        jikan_results = jikan_search_manga(q, limit=5, type_filter=type_filter)
        results = [{"id":f"j_{r['mal_id']}","title":(r.get("title_english") or r.get("title","?"))[:40],
                   "image":r.get("images",{}).get("jpg",{}).get("image_url",""),
                   "status":r.get("status",""), "tags":[g["name"] for g in r.get("genres",[])][:3]} for r in jikan_results]
    if not results:
        await msg.edit_text("❌ No results found.")
        return
    buttons = [[InlineKeyboardButton(f"📖 {r['title'][:40]}", callback_data=f"manga_{r['id']}")] for r in results[:5]]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await msg.edit_text(f"🔍 {type_filter.title()} results for *{q}*:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def caption_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /caption Attack on Titan")
        return
    msg = await update.message.reply_text(f"✍️ Generating caption for: {q}...")
    results = jikan_search_anime(q, limit=1)
    if not results:
        await msg.edit_text("❌ Anime not found.")
        return
    a = results[0]
    cap = await ai_caption(a)
    poster_url = a.get("images",{}).get("jpg",{}).get("large_image_url","") or a.get("images",{}).get("jpg",{}).get("image_url","")
    if poster_url:
        try:
            img_data = load_image_from_url(poster_url)
            if img_data:
                buf = io.BytesIO()
                img_data.convert("RGB").save(buf, "JPEG", quality=90)
                buf.seek(0)
                await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=buf, caption=cap)
                await msg.delete()
                return
        except: pass
    await msg.edit_text(cap)

async def thumbnail_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _gen_thumb(update, ctx, style="weebs")

async def thumb2_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _gen_thumb(update, ctx, style="kenshin")

async def thumb3_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _gen_thumb(update, ctx, style="campus")

async def _gen_thumb(update, ctx, style="weebs"):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text(f"Usage: /{style} Solo Leveling")
        return
    msg = await update.message.reply_text(f"🎨 Generating {style} thumbnail for: {q}...")
    results = jikan_search_anime(q, limit=1)
    if not results:
        await msg.edit_text("❌ Anime not found.")
        return
    a = results[0]
    try:
        buf = make_thumbnail(a, style=style)
        title = a.get("title_english") or a.get("title","")
        cap = make_caption(a)[:1024]
        await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=buf, caption=cap[:1024])
        await msg.delete()
    except Exception as e:
        logger.error(f"Thumbnail error: {e}")
        await msg.edit_text(f"❌ Thumbnail generation failed: {e}")

async def info_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = " ".join(ctx.args)
    if not q:
        await update.message.reply_text("Usage: /info Demon Slayer")
        return
    msg = await update.message.reply_text(f"📊 Fetching info: {q}...")
    results = jikan_search_anime(q, limit=1)
    if not results:
        await msg.edit_text("❌ Not found.")
        return
    a = get_anime_full(results[0]["mal_id"])
    if not a: a = results[0]
    title = a.get("title_english") or a.get("title","?")
    genres = ", ".join([g["name"] for g in a.get("genres",[])])
    themes = ", ".join([t["name"] for t in a.get("themes",[])])
    studios = ", ".join([s["name"] for s in a.get("studios",[])])
    text = (
        f"*{title}*\n"
        f"🎬 Type: {a.get('type','?')}  |  📺 Episodes: {a.get('episodes','?')}\n"
        f"⭐ Score: {a.get('score','?')}  |  📊 Rank: #{a.get('rank','?')}\n"
        f"📅 Year: {a.get('year','?')}  |  🟢 Status: {a.get('status','?')}\n"
        f"🎭 Genres: {genres}\n"
        f"💡 Themes: {themes}\n"
        f"🏢 Studio: {studios}\n\n"
        f"📝 {(a.get('synopsis','') or '')[:400]}"
    )
    poster_url = a.get("images",{}).get("jpg",{}).get("large_image_url","")
    if poster_url:
        try:
            img_data = load_image_from_url(poster_url)
            if img_data:
                buf = io.BytesIO()
                img_data.convert("RGB").save(buf,"JPEG",quality=90)
                buf.seek(0)
                await ctx.bot.send_photo(chat_id=update.effective_chat.id, photo=buf, caption=text, parse_mode="Markdown")
                await msg.delete()
                return
        except: pass
    await msg.edit_text(text, parse_mode="Markdown")

async def top_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔥 Fetching top airing anime...")
    try:
        r = requests.get(f"{JIKAN}/top/anime", params={"filter":"airing","limit":10}, timeout=10)
        data = r.json().get("data",[])
        if not data:
            await msg.edit_text("❌ Could not fetch top anime.")
            return
        text = "🔥 *Top Airing Anime:*\n\n"
        for i,a in enumerate(data[:10],1):
            t = a.get("title_english") or a.get("title","?")
            text += f"{i}. *{t}* — ⭐{a.get('score','?')}\n"
        await msg.edit_text(text, parse_mode="Markdown")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")

async def button_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.message.delete()
        return

    if data.startswith("anime_"):
        mal_id = int(data.split("_")[1])
        await query.message.edit_text("⏳ Loading anime info...")
        a = get_anime_full(mal_id)
        if not a:
            await query.message.edit_text("❌ Could not load anime.")
            return
        title = a.get("title_english") or a.get("title","?")
        genres = ", ".join([g["name"] for g in a.get("genres",[])])
        text = (f"*{title}*\n"
                f"⭐ {a.get('score','?')} | 📺 {a.get('episodes','?')} eps | {a.get('type','?')}\n"
                f"🎭 {genres}\n\n"
                f"{(a.get('synopsis','') or '')[:300]}...")
        buttons = [
            [InlineKeyboardButton("📝 Get Caption", callback_data=f"cap_{mal_id}"),
             InlineKeyboardButton("🖼 Thumbnail", callback_data=f"thumb_{mal_id}_weebs")],
            [InlineKeyboardButton("🎬 Kenshin Style", callback_data=f"thumb_{mal_id}_kenshin"),
             InlineKeyboardButton("📚 Campus Style", callback_data=f"thumb_{mal_id}_campus")],
            [InlineKeyboardButton("🔙 Back", callback_data="cancel")]
        ]
        poster = a.get("images",{}).get("jpg",{}).get("large_image_url","")
        try:
            img = load_image_from_url(poster)
            if img:
                buf=io.BytesIO(); img.convert("RGB").save(buf,"JPEG",quality=90); buf.seek(0)
                await ctx.bot.send_photo(chat_id=query.message.chat.id, photo=buf,
                    caption=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
                await query.message.delete()
                return
        except: pass
        await query.message.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("cap_"):
        mal_id = int(data.split("_")[1])
        await query.message.edit_text("✍️ Generating caption...")
        a = get_anime_full(mal_id)
        if not a:
            await query.message.edit_text("❌ Error.")
            return
        cap = await ai_caption(a)
        await query.message.edit_text(cap)

    elif data.startswith("thumb_"):
        parts = data.split("_")
        mal_id = int(parts[1])
        style = parts[2] if len(parts)>2 else "weebs"
        await query.message.edit_text(f"🎨 Generating {style} thumbnail...")
        a = get_anime_full(mal_id)
        if not a:
            await query.message.edit_text("❌ Error.")
            return
        try:
            buf = make_thumbnail(a, style=style)
            cap = make_caption(a)[:1024]
            await ctx.bot.send_photo(chat_id=query.message.chat.id, photo=buf, caption=cap)
            await query.message.delete()
        except Exception as e:
            await query.message.edit_text(f"❌ Thumbnail error: {e}")

    elif data.startswith("manga_"):
        mid = data.split("_",1)[1]
        await query.message.edit_text(f"📖 Loading manhwa/manga info...")
        # For now just show basic info
        await query.message.edit_text("📖 Manhwa/Manga selected! Use /caption or /thumbnail for more.")

async def text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle plain text as anime search"""
    q = update.message.text.strip()
    if len(q) < 2: return
    results = jikan_search_anime(q, limit=5)
    if not results:
        await update.message.reply_text(f"❌ '{q}' not found. Try /anime, /manhwa, or /manga.")
        return
    buttons = [[InlineKeyboardButton(
        f"{'🎬'} {(r.get('title_english') or r.get('title','?'))[:40]}",
        callback_data=f"anime_{r['mal_id']}"
    )] for r in results[:5]]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text(
        f"🔍 Found results for *{q}*:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

# ─── MAIN ─────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("anime", anime_cmd))
    app.add_handler(CommandHandler("manga", manga_cmd))
    app.add_handler(CommandHandler("manhwa", manhwa_cmd))
    app.add_handler(CommandHandler("manhua", manhua_cmd))
    app.add_handler(CommandHandler("caption", caption_cmd))
    app.add_handler(CommandHandler("thumbnail", thumbnail_cmd))
    app.add_handler(CommandHandler("thumb2", thumb2_cmd))
    app.add_handler(CommandHandler("thumb3", thumb3_cmd))
    app.add_handler(CommandHandler("info", info_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    logger.info("KENSHIN ANIME Bot starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
