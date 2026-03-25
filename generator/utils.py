"""Shared drawing utilities and font management."""

import io
import math
import os
import re
import urllib.request
import logging
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

logger = logging.getLogger(__name__)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
FONTS_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts")
LOGO_PATH  = os.path.join(ASSETS_DIR, "kenshin_logo.png")

W, H = 1280, 720

# ── Font registry ─────────────────────────────────────────────────────────────

_FONT_URLS = {
    "bebas":        "https://github.com/googlefonts/bebas-neue/raw/main/fonts/ttf/BebasNeue-Regular.ttf",
    "roboto_bold":  "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf",
    "roboto":       "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf",
    "roboto_light": "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Light.ttf",
    "oswald":       "https://github.com/googlefonts/OswaldFont/raw/main/fonts/ttf/Oswald-Bold.ttf",
}

_font_cache: dict[tuple, ImageFont.FreeTypeFont] = {}
_SYS_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def setup_fonts() -> None:
    os.makedirs(FONTS_DIR, exist_ok=True)
    for name, url in _FONT_URLS.items():
        path = os.path.join(FONTS_DIR, f"{name}.ttf")
        if not os.path.exists(path):
            try:
                logger.info(f"Downloading font: {name}")
                urllib.request.urlretrieve(url, path)
            except Exception as e:
                logger.warning(f"Font DL failed [{name}]: {e}")


def get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key in _font_cache:
        return _font_cache[key]

    path = os.path.join(FONTS_DIR, f"{name}.ttf")
    if os.path.exists(path):
        try:
            f = ImageFont.truetype(path, size)
            _font_cache[key] = f
            return f
        except Exception:
            pass
    for sp in _SYS_FONTS:
        if os.path.exists(sp):
            try:
                f = ImageFont.truetype(sp, size)
                _font_cache[key] = f
                return f
            except Exception:
                pass
    f = ImageFont.load_default()
    _font_cache[key] = f
    return f


# ── Image helpers ─────────────────────────────────────────────────────────────

def bytes_to_img(data: bytes) -> Optional[Image.Image]:
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def img_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=93, optimize=True)
    buf.seek(0)
    return buf.read()


def fill_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Resize + center-crop to exactly (tw, th)."""
    iw, ih = img.size
    ir, tr = iw / ih, tw / th
    if ir > tr:
        nw, nh = int(th * ir), th
    else:
        nw, nh = tw, int(tw / ir)
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - tw) // 2, (nh - th) // 2
    return img.crop((x, y, x + tw, y + th))


def fit_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((tw, th), Image.LANCZOS)
    return img


def darken(img: Image.Image, factor: float = 0.4) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


def blur(img: Image.Image, r: int = 18) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius=r))


def gradient(size: Tuple[int, int], direction: str,
             color: Tuple[int, int, int],
             a0: int = 0, a1: int = 220) -> Image.Image:
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)
    w, h = size
    if direction == "left":
        for x in range(w):
            a = int(a1 - (a1 - a0) * (x / w))
            draw.line([(x, 0), (x, h)], fill=(*color, a))
    elif direction == "right":
        for x in range(w):
            a = int(a0 + (a1 - a0) * (x / w))
            draw.line([(x, 0), (x, h)], fill=(*color, a))
    elif direction == "bottom":
        for y in range(h):
            a = int(a0 + (a1 - a0) * (y / h))
            draw.line([(0, y), (w, y)], fill=(*color, a))
    elif direction == "top":
        for y in range(h):
            a = int(a1 - (a1 - a0) * (y / h))
            draw.line([(0, y), (w, y)], fill=(*color, a))
    return ov


def vignette(size: Tuple[int, int], strength: int = 180) -> Image.Image:
    ov = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    w, h = size
    steps = 60
    for i in range(steps):
        a = int(strength * (i / steps) ** 2)
        d.rectangle([i * w // (steps * 2), i * h // (steps * 2),
                     w - i * w // (steps * 2), h - i * h // (steps * 2)],
                    outline=(0, 0, 0, a))
    return ov


def alpha_paste(base: Image.Image, overlay: Image.Image,
                pos: Tuple[int, int] = (0, 0)) -> Image.Image:
    base = base.convert("RGBA")
    overlay = overlay.convert("RGBA")
    base.paste(overlay, pos, overlay)
    return base


# ── Drawing helpers ───────────────────────────────────────────────────────────

def stroke_text(draw: ImageDraw.Draw, pos, text, font, fill,
                sw: int = 3, sf=(0, 0, 0)):
    x, y = pos
    for dx in range(-sw, sw + 1):
        for dy in range(-sw, sw + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=sf)
    draw.text(pos, text, font=font, fill=fill)


def shadow_text(draw: ImageDraw.Draw, pos, text, font, fill,
                offset: int = 4, sf=(0, 0, 0, 160)):
    x, y = pos
    draw.text((x + offset, y + offset), text, font=font, fill=sf)
    draw.text(pos, text, font=font, fill=fill)


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if font.getbbox(test)[2] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def rrect(draw: ImageDraw.Draw, xy, r: int, fill=None, outline=None, ow: int = 2):
    x1, y1, x2, y2 = xy
    if fill:
        draw.rectangle([x1 + r, y1, x2 - r, y2], fill=fill)
        draw.rectangle([x1, y1 + r, x2, y2 - r], fill=fill)
        for cx, cy in [(x1, y1), (x2 - 2*r, y1), (x1, y2 - 2*r), (x2 - 2*r, y2 - 2*r)]:
            draw.ellipse([cx, cy, cx + 2*r, cy + 2*r], fill=fill)
    if outline:
        draw.arc([x1, y1, x1 + 2*r, y1 + 2*r], 180, 270, fill=outline, width=ow)
        draw.arc([x2 - 2*r, y1, x2, y1 + 2*r], 270, 360, fill=outline, width=ow)
        draw.arc([x1, y2 - 2*r, x1 + 2*r, y2], 90, 180, fill=outline, width=ow)
        draw.arc([x2 - 2*r, y2 - 2*r, x2, y2], 0, 90, fill=outline, width=ow)
        draw.line([x1+r, y1, x2-r, y1], fill=outline, width=ow)
        draw.line([x1+r, y2, x2-r, y2], fill=outline, width=ow)
        draw.line([x1, y1+r, x1, y2-r], fill=outline, width=ow)
        draw.line([x2, y1+r, x2, y2-r], fill=outline, width=ow)


def score_color(s: float) -> Tuple[int, int, int]:
    if s >= 8.5: return (255, 215, 0)
    if s >= 7.5: return (0, 220, 120)
    if s >= 6.5: return (255, 165, 0)
    return (220, 60, 60)


def clean_text(text: str, max_len: int = 300) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\(Source:.*?\)", "", text)
    text = re.sub(r"\[Written by.*?\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def stamp_logo(base: Image.Image, pos: str = "bottom_right",
               ratio: float = 0.17, pad: int = 18) -> Image.Image:
    if not os.path.exists(LOGO_PATH):
        return base
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        lw = int(base.width * ratio)
        lh = int(lw * logo.height / logo.width)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        bw, bh = base.size
        positions = {
            "bottom_right": (bw - lw - pad, bh - lh - pad),
            "bottom_left":  (pad, bh - lh - pad),
            "top_right":    (bw - lw - pad, pad),
            "top_left":     (pad, pad),
        }
        x, y = positions.get(pos, (bw - lw - pad, bh - lh - pad))
        result = base.convert("RGBA")
        result.paste(logo, (x, y), logo)
        return result
    except Exception as e:
        logger.warning(f"Logo stamp error: {e}")
        return base
