"""
11 thumbnail styles for KENSHIN ANIME Bot.
Each style is inspired by a real Telegram manga/manhwa channel design.
"""

import math
import os
import random
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

from .utils import (
    W, H, get_font, fill_cover, fit_cover, darken, blur,
    gradient, vignette, alpha_paste,
    stroke_text, shadow_text, wrap, rrect, score_color,
    clean_text, stamp_logo,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  1. LIGHTNING  — KENSHIN signature, black + blue lightning + cover frame
# ═══════════════════════════════════════════════════════════════════════════════
def style_lightning(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 255))

    # faint manga-panel bg
    panel = fill_cover(cover.convert("RGBA"), W, H)
    panel = darken(panel, 0.12)
    panel = blur(panel, 4)
    bg = alpha_paste(bg, panel)

    draw = ImageDraw.Draw(bg)

    # lightning bolts
    rng = random.Random(99)
    def bolt(x1, y1, x2, y2, col, w, a):
        segs = 9
        pts = [(x1, y1)]
        for i in range(1, segs):
            px = x1 + (x2 - x1) * i / segs + rng.randint(-18, 18)
            py = y1 + (y2 - y1) * i / segs
            pts.append((px, py))
        pts.append((x2, y2))
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=(*col, a), width=w)
    for _ in range(10):
        bolt(rng.randint(0, W), 0, rng.randint(0, W), H, (0, 100, 255), 2, 70)
    for _ in range(4):
        bolt(rng.randint(0, W), 0, rng.randint(0, W), H, (80, 180, 255), 1, 35)

    # cover block (centre-right)
    ch = int(H * 0.84)
    cr = cover.width / cover.height
    cw = int(ch * cr)
    if cw > int(W * 0.40):
        cw = int(W * 0.40)
        ch = int(cw / cr)
    cdisplay = cover.convert("RGBA").resize((cw, ch), Image.LANCZOS)
    cx, cy = int(W * 0.55) - cw // 2, (H - ch) // 2

    # glow behind cover
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r in range(18, 0, -1):
        gd.rectangle([cx - r*4, cy - r*3, cx + cw + r*4, cy + ch + r*3],
                     outline=(0, 110, 255, max(0, 14 - r)))
    bg = alpha_paste(bg, glow)

    draw = ImageDraw.Draw(bg)
    for i in range(3):
        draw.rectangle([cx - i, cy - i, cx + cw + i, cy + ch + i],
                       outline=(0, 120 + i * 30, 255, 200 - i * 50))
    bg.paste(cdisplay, (cx, cy), cdisplay)
    draw = ImageDraw.Draw(bg)

    # right panel
    rx, rw = int(W * 0.76), int(W * 0.22)
    ty = 75

    f_title = get_font("bebas", 60)
    title = info.get("title", "Unknown")
    for line in wrap(title, f_title, rw)[:2]:
        stroke_text(draw, (rx, ty), line, f_title, (255, 255, 255),
                    sw=2, sf=(0, 70, 180))
        ty += 64

    draw.line([(rx, ty + 4), (W - 18, ty + 4)], fill=(0, 120, 255), width=2)
    ty += 16

    for g in info.get("genres", [])[:3]:
        gw = get_font("roboto_bold", 14).getbbox(g)[2] + 16
        if rx + gw > W - 12:
            break
        rrect(draw, (rx, ty, rx + gw, ty + 26), 4, fill=(0, 35, 110, 200))
        draw.text((rx + 8, ty + 5), g, font=get_font("roboto_bold", 14), fill=(100, 180, 255))
        ty += 34

    sc = info.get("score")
    if sc:
        sc = float(sc)
        stroke_text(draw, (rx, ty), f"{sc:.1f}",
                    get_font("bebas", 50), score_color(sc), sw=2, sf=(0, 45, 110))
        draw.text((rx + 82, ty + 18), "/ 10", font=get_font("roboto", 16), fill=(100, 150, 220))
        ty += 58

    f_m = get_font("roboto", 17)
    if info.get("year"):
        draw.text((rx, ty), f"📅 {info['year']}", font=f_m, fill=(150, 180, 230))
        ty += 26
    if info.get("episodes"):
        lbl = "Episodes" if info.get("type") == "anime" else "Chapters"
        draw.text((rx, ty), f"📖 {info['episodes']} {lbl}", font=f_m, fill=(150, 180, 230))

    # left vertical media type
    mtype = (info.get("type") or "ANIME").upper()
    f_v = get_font("bebas", 36)
    vx, vy = 18, H // 2 - len(mtype) * 18
    for ch_letter in mtype:
        draw.text((vx, vy), ch_letter, font=f_v, fill=(0, 90, 210, 200))
        vy += 38

    return stamp_logo(bg, "bottom_left", ratio=0.19, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  2. CRIMSON  — dark maroon + white card overlay + rating badge
# ═══════════════════════════════════════════════════════════════════════════════
def style_crimson(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (14, 4, 8, 255))
    cw = int(W * 0.63)
    cr = fill_cover(cover.convert("RGBA"), cw, H)
    bg.paste(cr, (0, 0), cr)
    bg = alpha_paste(bg, gradient((W, H), "left", (8, 2, 5), 0, 240))

    # atmospheric red glow
    atm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ad = ImageDraw.Draw(atm)
    for i in range(30):
        ad.ellipse([W//2 - 200 - i*15, H//2 - 100 - i*8,
                    W//2 + 200 + i*15, H//2 + 100 + i*8],
                   outline=(160, 15, 35, max(0, 28 - i)))
    bg = alpha_paste(bg, atm)

    # rating badge top-right
    draw = ImageDraw.Draw(bg)
    sc = info.get("score")
    if sc:
        sc = float(sc)
        rrect(draw, (W - 220, 28, W - 38, 86), 10, fill=(0, 0, 0, 165))
        draw.text((W - 214, 32), f"{sc:.1f}/10", font=get_font("bebas", 38),
                  fill=score_color(sc))
        draw.text((W - 214, 68), "RATING", font=get_font("roboto", 15), fill=(190, 190, 190))

    # white card
    cx, cy = int(W * 0.555), 75
    ccard_w, ccard_h = int(W * 0.41), H - 150
    card = Image.new("RGBA", (ccard_w, ccard_h), (255, 255, 255, 225))
    bg.paste(card, (cx, cy), card)
    draw = ImageDraw.Draw(bg)

    ty = cy + 18
    f_t = get_font("bebas", 52)
    for line in wrap(info.get("title", ""), f_t, ccard_w - 28)[:2]:
        draw.text((cx + 14, ty), line, font=f_t, fill=(115, 18, 38))
        ty += 56

    draw.line([(cx + 14, ty), (cx + ccard_w - 14, ty)], fill=(170, 25, 55), width=2)
    ty += 14

    synopsis = clean_text(info.get("synopsis", ""), 260)
    f_s = get_font("roboto", 17)
    for line in wrap(synopsis, f_s, ccard_w - 28)[:7]:
        draw.text((cx + 14, ty), line, font=f_s, fill=(38, 38, 38))
        ty += 23
    ty += 8

    gx = cx + 14
    f_g = get_font("roboto_bold", 13)
    for g in info.get("genres", [])[:4]:
        gw = f_g.getbbox(g)[2] + 14
        if gx + gw > cx + ccard_w - 14:
            break
        rrect(draw, (gx, ty, gx + gw, ty + 22), 4, fill=(115, 18, 38))
        draw.text((gx + 7, ty + 4), g, font=f_g, fill=(255, 255, 255))
        gx += gw + 6

    bty = cy + ccard_h - 48
    meta = []
    if info.get("year"):   meta.append(str(info["year"]))
    if info.get("episodes"): meta.append(f"{info['episodes']} EP")
    draw.text((cx + 14, bty), "  •  ".join(meta), font=get_font("roboto", 15), fill=(100, 100, 100))

    return stamp_logo(bg, "bottom_left", ratio=0.16, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. CAMPUS  — dark bg, big title left, character fills right (Manga Campus)
# ═══════════════════════════════════════════════════════════════════════════════
def style_campus(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (8, 8, 12, 255))

    # Character art right half
    art_w = int(W * 0.55)
    art = fill_cover(cover.convert("RGBA"), art_w, H)
    bg.paste(art, (W - art_w, 0), art)
    # blend left
    bg = alpha_paste(bg, gradient((W, H), "right", (8, 8, 12), 240, 0))

    # giant watermark letter behind title
    draw = ImageDraw.Draw(bg)
    f_wm = get_font("bebas", 380)
    wm_letter = (info.get("title") or "K")[0].upper()
    wb = f_wm.getbbox(wm_letter)
    draw.text((30 - 20, H // 2 - (wb[3] - wb[1]) // 2 - 20),
              wm_letter, font=f_wm, fill=(255, 255, 255, 18))

    # meta line
    f_meta = get_font("roboto", 18)
    meta_parts = []
    if info.get("year"):      meta_parts.append(str(info["year"]))
    rating_text = ""
    if info.get("score"):
        meta_parts.append(f"⭐ {float(info['score']):.1f}/10")
    if info.get("episodes"):
        lbl = "CHP" if info.get("type") != "anime" else "EP"
        meta_parts.append(f"{info['episodes']} {lbl}")
    genres = info.get("genres", [])[:3]
    if genres:
        meta_parts.append(", ".join(genres))
    draw.text((80, 52), "  |  ".join(meta_parts), font=f_meta, fill=(200, 200, 200))

    # Big title
    f_title = get_font("bebas", 100)
    ty = 100
    for line in wrap(info.get("title", ""), f_title, int(W * 0.48) - 80)[:2]:
        stroke_text(draw, (80, ty), line, f_title, (255, 255, 255), sw=3, sf=(0, 0, 0))
        ty += 105

    # Synopsis
    synopsis = clean_text(info.get("synopsis", ""), 280)
    f_syn = get_font("roboto", 19)
    ty += 8
    for line in wrap(synopsis, f_syn, int(W * 0.46) - 80)[:6]:
        draw.text((80, ty), line, font=f_syn, fill=(210, 210, 210))
        ty += 26
    ty += 12

    # READ NOW button
    btn_w, btn_h = 155, 44
    rrect(draw, (80, ty, 80 + btn_w, ty + btn_h), 5, fill=(130, 60, 200))
    draw.text((90, ty + 10), "📖 READ NOW", font=get_font("roboto_bold", 16), fill=(255, 255, 255))

    # MY LIST button
    mx = 80 + btn_w + 16
    rrect(draw, (mx, ty, mx + 130, ty + btn_h), 5, fill=(0, 0, 0, 0),
          outline=(200, 200, 200), ow=2)
    draw.text((mx + 16, ty + 10), "+ MY LIST", font=get_font("roboto_bold", 16), fill=(200, 200, 200))

    # Avg rating bottom-left
    sc = info.get("score")
    if sc:
        sc = float(sc)
        draw.ellipse([80, H - 80, 115, H - 45], outline=(255, 255, 255), width=2)
        draw.text((88, H - 74), "👍", font=get_font("roboto", 14), fill=(255, 255, 255))
        draw.text((122, H - 72), f"Avg. Rating - {int(sc * 10)}%",
                  font=get_font("roboto_bold", 18), fill=(255, 255, 255))

    return stamp_logo(bg, "top_right", ratio=0.14, pad=12).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. RAGNAROK  — blurred bg, frosted glass card, small cover thumbnail left
# ═══════════════════════════════════════════════════════════════════════════════
def style_ragnarok(cover: Image.Image, info: dict) -> Image.Image:
    # Blurred full bg
    bg_full = fill_cover(cover.convert("RGBA"), W, H)
    bg_full = darken(bg_full, 0.45)
    bg_full = blur(bg_full, 16)
    bg = bg_full.convert("RGBA")

    # Dark overlay
    bg = alpha_paste(bg, Image.new("RGBA", (W, H), (0, 0, 30, 130)))

    # Season label top
    draw = ImageDraw.Draw(bg)
    season_label = info.get("format") or info.get("type", "").upper()
    if season_label:
        draw.text((W // 2 - 100, 28), season_label.upper(),
                  font=get_font("oswald", 40), fill=(0, 220, 200))

    # Glass card
    card_x, card_y, card_w, card_h = 88, 85, W - 110, H - 110
    glass = Image.new("RGBA", (card_w, card_h), (20, 20, 50, 200))
    bg.paste(glass, (card_x, card_y), glass)
    draw = ImageDraw.Draw(bg)
    draw.rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                   outline=(255, 255, 255, 40), width=1)

    # Small cover inside card (left)
    sc_h = int(card_h * 0.88)
    sc_ratio = cover.width / cover.height
    sc_w = int(sc_h * sc_ratio)
    if sc_w > int(card_w * 0.40):
        sc_w = int(card_w * 0.40)
        sc_h = int(sc_w / sc_ratio)
    sc_img = cover.convert("RGBA").resize((sc_w, sc_h), Image.LANCZOS)
    sc_x = card_x + 18
    sc_y = card_y + (card_h - sc_h) // 2
    draw.rectangle([sc_x - 2, sc_y - 2, sc_x + sc_w + 2, sc_y + sc_h + 2],
                   outline=(255, 255, 255, 60), width=1)
    bg.paste(sc_img, (sc_x, sc_y), sc_img)
    draw = ImageDraw.Draw(bg)

    # Info right of cover
    ix = sc_x + sc_w + 24
    iy = card_y + 22
    iw = card_x + card_w - ix - 10

    # TITLE label
    draw.text((ix, iy), "TITLE", font=get_font("roboto_bold", 15), fill=(180, 180, 180))
    iy += 22

    f_title = get_font("bebas", 62)
    for line in wrap(info.get("title", ""), f_title, iw)[:2]:
        draw.text((ix, iy), line, font=f_title, fill=(255, 255, 255))
        iy += 66

    # Genre
    draw.text((ix, iy), "GENRE:", font=get_font("roboto_bold", 16), fill=(180, 180, 180))
    draw.text((ix + 76, iy + 1), ", ".join(info.get("genres", [])[:4]),
              font=get_font("roboto", 16), fill=(255, 255, 255))
    iy += 28

    # Stars + score
    sc = info.get("score")
    if sc:
        sc = float(sc)
        stars = int(sc / 2)
        star_str = "★" * stars + "☆" * (5 - stars)
        draw.text((ix, iy), star_str, font=get_font("roboto_bold", 22), fill=(255, 200, 0))
        draw.text((ix + 130, iy + 2), f"{sc:.2f}", font=get_font("roboto_bold", 22),
                  fill=(255, 255, 255))
        iy += 32

    # Synopsis
    synopsis = clean_text(info.get("synopsis", ""), 380)
    f_s = get_font("roboto", 17)
    for line in wrap(synopsis, f_s, iw)[:8]:
        draw.text((ix, iy), line, font=f_s, fill=(220, 220, 230))
        iy += 22

    # READ / MY LIST buttons bottom
    by = card_y + card_h - 58
    rrect(draw, (ix, by, ix + 120, by + 42), 6, fill=(130, 60, 200))
    draw.text((ix + 20, by + 11), "READ", font=get_font("roboto_bold", 18), fill=(255, 255, 255))
    rrect(draw, (ix + 136, by, ix + 266, by + 42), 6, fill=(0, 0, 0, 0),
          outline=(255, 255, 255, 120), ow=2)
    draw.text((ix + 148, by + 11), "MY LIST", font=get_font("roboto_bold", 18), fill=(255, 255, 255))

    return stamp_logo(bg, "top_right", ratio=0.14, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  5. ARC  — dark, character left with arc overlay, BIG title right, synopsis
# ═══════════════════════════════════════════════════════════════════════════════
def style_arc(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (10, 10, 12, 255))

    # character left half (blurred slightly)
    art_w = int(W * 0.50)
    art = fill_cover(cover.convert("RGBA"), art_w, H)
    bg.paste(art, (0, 0), art)

    # arc divider (orange/gold)
    arc_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    arc_draw = ImageDraw.Draw(arc_img)
    arc_draw.ellipse([-300, -200, 700, H + 200], outline=(200, 120, 0, 180), width=6)
    arc_draw.ellipse([-320, -220, 720, H + 220], outline=(255, 160, 0, 80), width=3)
    bg = alpha_paste(bg, arc_img)
    bg = alpha_paste(bg, gradient((W, H), "right", (10, 10, 12), 240, 0))

    draw = ImageDraw.Draw(bg)

    # Right side
    rx, rw = int(W * 0.53), int(W * 0.44)
    ty = 60

    # Big title
    f_t = get_font("bebas", 95)
    title = info.get("title", "")
    for line in wrap(title.upper(), f_t, rw)[:2]:
        stroke_text(draw, (rx, ty), line, f_t, (255, 255, 255), sw=3, sf=(0, 0, 0))
        ty += 100

    # Synopsis label
    ty += 8
    rrect(draw, (rx, ty, rx + 160, ty + 32), 6, fill=(200, 120, 0))
    draw.text((rx + 12, ty + 7), "SYNOPSIS:", font=get_font("roboto_bold", 16),
              fill=(255, 255, 255))
    ty += 42

    synopsis = clean_text(info.get("synopsis", ""), 350)
    f_s = get_font("roboto", 18)
    for line in wrap(synopsis, f_s, rw)[:7]:
        draw.text((rx, ty), line, font=f_s, fill=(215, 210, 200))
        ty += 24

    # channel/credit line bottom
    f_tag = get_font("roboto_bold", 15)
    draw.text((rx, H - 42), "@KenshinAnime", font=f_tag, fill=(180, 180, 180))

    return stamp_logo(bg, "bottom_right", ratio=0.16, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  6. ZENITH  — dark blue hexagons, cover right, score circle badge
# ═══════════════════════════════════════════════════════════════════════════════
def style_zenith(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (6, 14, 32, 255))
    draw = ImageDraw.Draw(bg)

    # hexagons
    hs = 42
    for row in range(H // hs + 3):
        for col in range(W // hs + 3):
            cx = col * hs * 1.5 + (hs * 0.75 if row % 2 else 0)
            cy = row * hs * 0.87
            pts = [(cx + hs * 0.44 * math.cos(math.pi / 3 * i - math.pi / 6),
                    cy + hs * 0.44 * math.sin(math.pi / 3 * i - math.pi / 6)) for i in range(6)]
            draw.polygon(pts, outline=(18, 38, 88, 110))

    # cover right
    art_w = int(W * 0.52)
    art = fill_cover(cover.convert("RGBA"), art_w, H)
    bg.paste(art, (W - art_w, 0), art)
    bg = alpha_paste(bg, gradient((W, H), "right", (6, 14, 32), 255, 0))

    draw = ImageDraw.Draw(bg)
    # blue accent bar
    draw.line([(48, 75), (48, H - 75)], fill=(0, 120, 255), width=4)

    f_t = get_font("bebas", 70)
    ty = 75
    for line in wrap((info.get("title") or "").upper(), f_t, int(W * 0.48) - 80)[:2]:
        stroke_text(draw, (68, ty), line, f_t, (255, 255, 255), sw=2, sf=(0, 70, 200))
        ty += 74

    if info.get("year"):
        draw.text((70, ty + 4), str(info["year"]), font=get_font("roboto_bold", 26),
                  fill=(90, 150, 255))
        ty += 38
    if info.get("format"):
        draw.text((70, ty + 4), info["format"].upper(), font=get_font("roboto", 21),
                  fill=(70, 120, 200))
        ty += 30

    synopsis = clean_text(info.get("synopsis", ""), 210)
    ty += 14
    f_s = get_font("roboto_light", 18)
    for line in wrap(synopsis, f_s, int(W * 0.46) - 80)[:5]:
        draw.text((70, ty), line, font=f_s, fill=(175, 195, 228))
        ty += 25
    ty += 10

    gx = 70
    f_g = get_font("roboto_bold", 14)
    for g in info.get("genres", [])[:4]:
        gw = f_g.getbbox(g)[2] + 16
        if gx + gw > int(W * 0.48):
            break
        rrect(draw, (gx, ty, gx + gw, ty + 25), 4, fill=(0, 55, 170, 190))
        draw.text((gx + 8, ty + 5), g, font=f_g, fill=(170, 215, 255))
        gx += gw + 7
    ty += 38

    sc = info.get("score")
    if sc:
        sc = float(sc)
        rx, ry = 110, ty + 38
        draw.ellipse([rx - 48, ry - 48, rx + 48, ry + 48], fill=(0, 25, 80, 220))
        draw.ellipse([rx - 48, ry - 48, rx + 48, ry + 48], outline=score_color(sc), width=3)
        st = f"{sc:.1f}"
        sb = get_font("bebas", 30).getbbox(st)
        draw.text((rx - (sb[2] - sb[0]) // 2, ry - 18), st,
                  font=get_font("bebas", 30), fill=score_color(sc))
        draw.text((rx - 14, ry + 14), "SCORE", font=get_font("roboto", 12), fill=(140, 175, 225))

    return stamp_logo(bg, "bottom_right", ratio=0.17, pad=16).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  7. NEON  — blurred bg, neon pink/purple border + cover left
# ═══════════════════════════════════════════════════════════════════════════════
def style_neon(cover: Image.Image, info: dict) -> Image.Image:
    bg_full = fill_cover(cover.convert("RGBA"), W, H)
    bg = darken(blur(bg_full, 22), 0.22).convert("RGBA")
    bg = alpha_paste(bg, Image.new("RGBA", (W, H), (5, 0, 18, 175)))

    draw = ImageDraw.Draw(bg)
    for i in range(7):
        a = max(0, 200 - i * 28)
        c = (255, 20 + i * 18, 180, a)
        draw.rectangle([i, i, W - i, H - i], outline=c)

    # cover left
    ch = int(H * 0.82)
    cr = cover.width / cover.height
    cw = min(int(ch * cr), int(W * 0.44))
    ch = int(cw / cr)
    cimg = cover.convert("RGBA").resize((cw, ch), Image.LANCZOS)
    cxpos, cypos = int(W * 0.25) - cw // 2, (H - ch) // 2
    bg.paste(cimg, (cxpos, cypos), cimg)

    draw = ImageDraw.Draw(bg)
    # right info
    rx, rw = int(W * 0.50), int(W * 0.46)
    ty = 78

    f_t = get_font("bebas", 62)
    for line in wrap(info.get("title", ""), f_t, rw - 20)[:2]:
        stroke_text(draw, (rx, ty), line, f_t, (255, 100, 220),
                    sw=3, sf=(100, 0, 80))
        ty += 66

    draw.line([(rx, ty + 4), (rx + rw - 30, ty + 4)], fill=(255, 0, 200, 200), width=2)
    ty += 18

    gx = rx
    f_g = get_font("roboto_bold", 15)
    for g in info.get("genres", [])[:4]:
        gw = f_g.getbbox(g)[2] + 16
        if gx + gw > rx + rw - 10:
            break
        rrect(draw, (gx, ty, gx + gw, ty + 27), 6,
              fill=(75, 0, 115, 190), outline=(195, 0, 255, 200), ow=1)
        draw.text((gx + 8, ty + 6), g, font=f_g, fill=(215, 145, 255))
        gx += gw + 9
    ty += 38

    synopsis = clean_text(info.get("synopsis", ""), 250)
    f_s = get_font("roboto", 18)
    for line in wrap(synopsis, f_s, rw - 20)[:6]:
        draw.text((rx, ty), line, font=f_s, fill=(200, 180, 222))
        ty += 24
    ty += 12

    sc = info.get("score")
    if sc:
        sc = float(sc)
        draw.text((rx, ty), f"{sc:.1f}", font=get_font("bebas", 44), fill=(255, 50, 200))
        draw.text((rx + 74, ty + 15), "/ 10", font=get_font("roboto", 16), fill=(175, 128, 200))

    return stamp_logo(bg, "bottom_right", ratio=0.16, pad=18).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  8. FROSTED  — manga-panel bg (B&W), frosted glass info card centre
# ═══════════════════════════════════════════════════════════════════════════════
def style_frosted(cover: Image.Image, info: dict) -> Image.Image:
    # B&W manga bg
    bg_full = fill_cover(cover.convert("RGBA"), W, H)
    grey = bg_full.convert("L").convert("RGBA")
    dark = darken(grey, 0.35)
    dark = blur(dark, 3)
    bg = dark.convert("RGBA")

    # paper/halftone noise overlay
    dot_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot_layer)
    rng = random.Random(7)
    for _ in range(2500):
        x, y = rng.randint(0, W), rng.randint(0, H)
        r = rng.randint(1, 3)
        a = rng.randint(15, 50)
        dd.ellipse([x, y, x + r, y + r], fill=(200, 200, 200, a))
    bg = alpha_paste(bg, dot_layer)

    # frosted glass card
    cx, cy, cw, ch = 120, 60, int(W * 0.60), H - 115
    glass = Image.new("RGBA", (cw, ch), (30, 30, 40, 210))
    bg.paste(glass, (cx, cy), glass)
    draw = ImageDraw.Draw(bg)
    draw.rectangle([cx, cy, cx + cw, cy + ch], outline=(255, 255, 255, 50), width=1)

    # small cover thumbnail inside card top
    tc_h = int(ch * 0.40)
    tc_ratio = cover.width / cover.height
    tc_w = int(tc_h * tc_ratio)
    if tc_w > int(cw * 0.38):
        tc_w = int(cw * 0.38)
        tc_h = int(tc_w / tc_ratio)
    tc_img = fill_cover(cover.convert("RGBA"), tc_w, tc_h)
    tc_x, tc_y = cx + (cw - tc_w) // 2, cy + 14
    bg.paste(tc_img, (tc_x, tc_y), tc_img)
    draw = ImageDraw.Draw(bg)

    ty = tc_y + tc_h + 16

    # Title
    f_t = get_font("bebas", 54)
    title = info.get("title", "")
    title_bnd = f_t.getbbox(title)
    title_x = cx + (cw - (title_bnd[2] - title_bnd[0])) // 2
    draw.text((title_x, ty), title, font=f_t, fill=(255, 255, 255))
    ty += 58

    # Genres (centered pills)
    genres = info.get("genres", [])[:4]
    f_g = get_font("roboto_bold", 15)
    pill_widths = [f_g.getbbox(g)[2] + 18 for g in genres]
    total_pills = sum(pill_widths) + 8 * (len(genres) - 1)
    total_clips = min(total_pills, cw - 40)
    gx = cx + (cw - total_clips) // 2
    for i, g in enumerate(genres):
        gw = pill_widths[i]
        rrect(draw, (gx, ty, gx + gw, ty + 28), 14, fill=(0, 0, 0, 0),
              outline=(255, 255, 255, 180), ow=1)
        draw.text((gx + 9, ty + 7), g, font=f_g, fill=(255, 255, 255))
        gx += gw + 8
    ty += 38

    draw.line([(cx + 20, ty), (cx + cw - 20, ty)], fill=(255, 255, 255, 60), width=1)
    ty += 16

    # Synopsis
    synopsis = clean_text(info.get("synopsis", ""), 300)
    f_s = get_font("roboto", 16)
    for line in wrap(synopsis, f_s, cw - 40)[:5]:
        draw.text((cx + 20, ty), line, font=f_s, fill=(220, 220, 220))
        ty += 22

    # Rating + status bottom right of card
    sc = info.get("score")
    if sc:
        sc = float(sc)
        f_sc = get_font("bebas", 30)
        sc_txt = f"Rating: {sc:.1f}/10"
        sb = f_sc.getbbox(sc_txt)
        draw.text((cx + cw - (sb[2] - sb[0]) - 14, cy + ch - 42), sc_txt,
                  font=f_sc, fill=score_color(sc))

    return stamp_logo(bg, "bottom_right", ratio=0.16, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  9. MINIMAL  — clean dark split, blue/yellow accent lines, bold title
# ═══════════════════════════════════════════════════════════════════════════════
def style_minimal(cover: Image.Image, info: dict) -> Image.Image:
    bg = Image.new("RGBA", (W, H), (10, 10, 16, 255))
    draw = ImageDraw.Draw(bg)
    draw.polygon([(0, 0), (210, 0), (0, 210)], fill=(25, 75, 215))
    draw.polygon([(W, 0), (W - 95, 0), (W, 95)], fill=(12, 38, 115, 200))

    art_w = int(W * 0.54)
    art = fill_cover(cover.convert("RGBA"), art_w, H)
    bg.paste(art, (W - art_w, 0), art)
    bg = alpha_paste(bg, gradient((W, H), "right", (10, 10, 16), 255, 20))

    draw = ImageDraw.Draw(bg)
    draw.line([(48, 78), (48, H - 78)], fill=(220, 180, 0), width=5)

    mtype = (info.get("type") or "anime").upper()
    draw.text((68, 58), f"KENSHIN ANIME  ·  {mtype}", font=get_font("roboto_bold", 17),
              fill=(75, 118, 200))

    f_t = get_font("bebas", 82)
    ty = 105
    for line in wrap((info.get("title") or "").upper(), f_t, int(W * 0.42) - 80)[:2]:
        draw.text((68, ty), line, font=f_t, fill=(255, 255, 255))
        ty += 86

    synopsis = clean_text(info.get("synopsis", ""), 190)
    f_s = get_font("roboto", 19)
    ty += 8
    for line in wrap(synopsis, f_s, int(W * 0.42) - 80)[:4]:
        draw.text((68, ty), line, font=f_s, fill=(165, 170, 190))
        ty += 27

    genres = info.get("genres", [])[:3]
    gy = H // 2 - len(genres) * 34
    for g in genres:
        draw.text((16, gy), g, font=get_font("roboto_bold", 14), fill=(95, 145, 255))
        gy += 34

    by = H - 68
    rrect(draw, (68, by, 220, by + 42), 4, fill=(0, 75, 215))
    draw.text((92, by + 10), "JOIN NOW", font=get_font("roboto_bold", 18), fill=(255, 255, 255))
    rrect(draw, (234, by, 435, by + 42), 4, fill=(0, 0, 0, 0),
          outline=(75, 118, 200), ow=2)
    draw.text((252, by + 10), "KENSHIN ANIME", font=get_font("roboto_bold", 18),
              fill=(75, 118, 200))

    return stamp_logo(bg, "bottom_right", ratio=0.15, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  10. DEMON  — dark bg, red glow border, small cover, atmospheric (Weebs)
# ═══════════════════════════════════════════════════════════════════════════════
def style_demon(cover: Image.Image, info: dict) -> Image.Image:
    bg_full = fill_cover(cover.convert("RGBA"), W, H)
    bg = darken(bg_full, 0.38).convert("RGBA")
    bg = alpha_paste(bg, vignette((W, H), 200))

    bot_ov = gradient((W, H), "bottom", (0, 0, 0), 0, 200)
    bg = alpha_paste(bg, bot_ov)

    border_l = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border_l)
    for i in range(8):
        bd.rectangle([i, i, W - i, H - i], outline=(195, 0, 28, max(0, 200 - i * 22)))
    bg = alpha_paste(bg, border_l)

    draw = ImageDraw.Draw(bg)

    # small cover display bottom-left
    sc_h = int(H * 0.44)
    sc_r = cover.width / cover.height
    sc_w = int(sc_h * sc_r)
    sc_img = cover.convert("RGBA").resize((sc_w, sc_h), Image.LANCZOS)
    sx, sy = 38, H - sc_h - 58
    draw.rectangle([sx - 2, sy - 2, sx + sc_w + 2, sy + sc_h + 2], outline=(175, 0, 28), width=2)
    bg.paste(sc_img, (sx, sy), sc_img)
    draw = ImageDraw.Draw(bg)

    # Title top
    f_t = get_font("bebas", 68)
    ty = 42
    for line in wrap((info.get("title") or "").upper(), f_t, int(W * 0.67))[:2]:
        stroke_text(draw, (38, ty), line, f_t, (255, 255, 255), sw=3, sf=(150, 0, 18))
        ty += 74

    # buttons
    by = ty + 12
    rrect(draw, (38, by, 215, by + 46), 23, fill=(255, 255, 255))
    draw.text((64, by + 12), "READ NOW", font=get_font("roboto_bold", 20), fill=(15, 0, 0))
    rrect(draw, (228, by, 294, by + 46), 23, fill=(0, 0, 0, 110),
          outline=(255, 255, 255), ow=2)
    draw.text((244, by + 12), "+", font=get_font("roboto_bold", 20), fill=(255, 255, 255))
    ty = by + 60

    draw.text((38, ty), f"SELECTED {(info.get('type') or 'MANHWA').upper()}",
              font=get_font("roboto_bold", 17), fill=(195, 195, 195))
    ty += 28

    # synopsis beside small cover
    ix = sx + sc_w + 18
    iw = int(W * 0.66) - ix
    f_s = get_font("roboto", 17)
    ity = sy + 8
    for line in wrap(clean_text(info.get("synopsis", ""), 200), f_s, iw)[:6]:
        draw.text((ix, ity), line, font=f_s, fill=(215, 205, 205))
        ity += 23

    # genre pills bottom
    genres = info.get("genres", [])[:4]
    gx = ix
    f_g = get_font("roboto_bold", 15)
    gy = H - 50
    for g in genres:
        gw = f_g.getbbox(g)[2] + 18
        if gx + gw > W * 0.75:
            break
        rrect(draw, (gx, gy, gx + gw, gy + 30), 15, fill=(0, 0, 0, 0),
              outline=(255, 255, 255), ow=1)
        draw.text((gx + 9, gy + 7), g, font=f_g, fill=(255, 255, 255))
        gx += gw + 9

    # rating circle bottom-right
    sc = info.get("score")
    if sc:
        sc = float(sc)
        rx_, ry_ = W - 118, H - 125
        draw.ellipse([rx_ - 58, ry_ - 58, rx_ + 58, ry_ + 58], fill=(28, 28, 28, 205))
        draw.ellipse([rx_ - 58, ry_ - 58, rx_ + 58, ry_ + 58], outline=score_color(sc), width=5)
        pt = f"{int(sc * 10)}%"
        pb = get_font("bebas", 32).getbbox(pt)
        draw.text((rx_ - (pb[2] - pb[0]) // 2, ry_ - 20), pt,
                  font=get_font("bebas", 32), fill=score_color(sc))
        draw.text((rx_ - 38, ry_ + 16), "AVG RATING:", font=get_font("roboto", 12),
                  fill=(195, 195, 195))

    return stamp_logo(bg, "bottom_right", ratio=0.15, pad=14).convert("RGB")


# ═══════════════════════════════════════════════════════════════════════════════
#  11. VERTICAL  — big art bg, vertical crossword-style title on right
# ═══════════════════════════════════════════════════════════════════════════════
def style_vertical(cover: Image.Image, info: dict) -> Image.Image:
    # Background: big banner or cover
    bg_full = fill_cover(cover.convert("RGBA"), W, H)
    bg = darken(bg_full, 0.50).convert("RGBA")
    bg = alpha_paste(bg, gradient((W, H), "bottom", (5, 5, 20), 0, 210))

    draw = ImageDraw.Draw(bg)

    # Left glass card for synopsis
    cx, cy, cw, ch = 50, 50, 380, H - 120
    glass_card = Image.new("RGBA", (cw, ch), (10, 12, 30, 190))
    bg.paste(glass_card, (cx, cy), glass_card)
    draw = ImageDraw.Draw(bg)
    draw.rectangle([cx, cy, cx + cw, cy + ch], outline=(255, 255, 255, 40), width=1)

    # profile-style avatar of cover (top of card)
    av_size = 70
    av = fill_cover(cover.convert("RGBA"), av_size, av_size)
    mask = Image.new("L", (av_size, av_size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, av_size, av_size], fill=255)
    av.putalpha(mask)
    ax, ay = cx + 14, cy + 16
    draw.ellipse([ax - 2, ay - 2, ax + av_size + 2, ay + av_size + 2],
                 outline=(255, 255, 255, 100), width=2)
    bg.paste(av, (ax, ay), av)
    draw = ImageDraw.Draw(bg)

    ty = cy + av_size + 32

    draw.text((cx + 14, ty), "SYNOPSIS", font=get_font("roboto_bold", 16), fill=(200, 200, 200))
    ty += 24

    synopsis = clean_text(info.get("synopsis", ""), 260)
    f_s = get_font("roboto", 16)
    for line in wrap(synopsis, f_s, cw - 28)[:7]:
        draw.text((cx + 14, ty), line, font=f_s, fill=(200, 200, 215))
        ty += 22
    ty += 10

    draw.line([(cx + 14, ty), (cx + cw - 14, ty)], fill=(255, 255, 255, 60), width=1)
    ty += 14

    f_g = get_font("roboto_bold", 14)
    gx = cx + 14
    for g in info.get("genres", [])[:4]:
        gw = f_g.getbbox(g)[2] + 14
        if gx + gw > cx + cw - 14:
            break
        rrect(draw, (gx, ty, gx + gw, ty + 24), 12, fill=(0, 0, 0, 0),
              outline=(255, 255, 255, 130), ow=1)
        draw.text((gx + 7, ty + 5), g, font=f_g, fill=(255, 255, 255))
        gx += gw + 8
    ty += 36

    # Nightowls-style channel label
    draw.text((cx + 14, cy + ch - 42), f">>> KENSHIN ANIME",
              font=get_font("roboto_bold", 15), fill=(180, 180, 200))

    # Right side: vertical crossword-style title
    title = info.get("title", "UNKNOWN").upper()
    vx = int(W * 0.72)
    vy = 48
    f_v = get_font("bebas", 48)
    col_w = 55
    words = title.split()[:3]
    for wi, word in enumerate(words):
        wx = vx + wi * (col_w + 4)
        wy = vy
        for letter in word:
            if wy + 55 > H - 60:
                break
            # cell bg
            draw.rectangle([wx, wy, wx + col_w, wy + 50], fill=(255, 255, 255, 220))
            lb = f_v.getbbox(letter)
            lx = wx + (col_w - (lb[2] - lb[0])) // 2
            draw.text((lx, wy + 2), letter, font=f_v, fill=(10, 10, 20))
            wy += 54

    # Bottom bar with meta
    by = H - 60
    bg_bar = Image.new("RGBA", (W, 60), (0, 0, 0, 185))
    bg.paste(bg_bar, (0, by), bg_bar)
    draw = ImageDraw.Draw(bg)

    meta = info.get("title", "")[:40]
    sc = info.get("score")
    if sc:
        meta += f"  •  ⭐ {float(sc):.1f}"
    if info.get("year"):
        meta += f"  •  {info['year']}"
    draw.text((cx + 14, by + 16), meta, font=get_font("roboto_bold", 18), fill=(255, 255, 255))

    return stamp_logo(bg, "bottom_right", ratio=0.16, pad=10).convert("RGB")


# ── Style registry ────────────────────────────────────────────────────────────
STYLE_FUNCS: dict = {
    "lightning": style_lightning,
    "crimson":   style_crimson,
    "campus":    style_campus,
    "ragnarok":  style_ragnarok,
    "arc":       style_arc,
    "zenith":    style_zenith,
    "neon":      style_neon,
    "frosted":   style_frosted,
    "minimal":   style_minimal,
    "demon":     style_demon,
    "vertical":  style_vertical,
}
