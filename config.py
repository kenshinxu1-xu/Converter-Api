import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")

# ── Optional ──────────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI", "")
CHANNEL_URL  = os.getenv("CHANNEL_URL", "https://t.me/KenshinAnime")
BOT_USERNAME = os.getenv("BOT_USERNAME", "KenshinAnimeBot")
ADMIN_IDS    = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

_raw = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS: list[int] = [int(x) for x in _raw.split(",") if x.strip().isdigit()]

THUMB_W, THUMB_H = 1280, 720

STYLES: dict[str, dict] = {
    "lightning": {"emoji": "⚡", "name": "Lightning",  "desc": "Black + blue lightning — KENSHIN signature"},
    "crimson":   {"emoji": "🔴", "name": "Crimson",    "desc": "Dark red + white card overlay + rating badge"},
    "campus":    {"emoji": "🎓", "name": "Campus",     "desc": "Dark bg, giant watermark title, character right"},
    "ragnarok":  {"emoji": "⚔️", "name": "Ragnarok",   "desc": "Blurred bg + frosted glass card + cover thumbnail"},
    "arc":       {"emoji": "🌑", "name": "Arc",        "desc": "Dark + golden arc divider + big synopsis"},
    "zenith":    {"emoji": "🔵", "name": "Zenith",     "desc": "Navy hexagon pattern + score circle badge"},
    "neon":      {"emoji": "💜", "name": "Neon",       "desc": "Neon pink/purple glowing border"},
    "frosted":   {"emoji": "❄️",  "name": "Frosted",    "desc": "B&W manga panel bg + frosted glass card"},
    "minimal":   {"emoji": "⬛", "name": "Minimal",    "desc": "Clean split layout, yellow accent, blue buttons"},
    "demon":     {"emoji": "👹", "name": "Demon",      "desc": "Dark atmospheric + red glow border + rating donut"},
    "vertical":  {"emoji": "📐", "name": "Vertical",   "desc": "Big art bg + crossword-style vertical title"},
}
