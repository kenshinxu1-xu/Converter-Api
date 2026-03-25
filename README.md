# ⚡ KENSHIN ANIME Thumbnail Bot

A **fast**, **multi-API** Telegram bot that generates stunning anime / manga / manhwa thumbnails with KENSHIN ANIME branding — automatically.

---

## ✨ Features

- **11 unique thumbnail styles** (1280×720, broadcast-ready)
- **3 APIs in parallel** — Jikan (MAL) + AniList + Kitsu
- **30-minute result caching** — instant repeat searches
- **Async everywhere** — non-blocking, handles many users at once
- **Auto font download** at startup
- **KENSHIN ANIME logo** stamped on every thumbnail
- Supports **Anime**, **Manga**, and **Manhwa**

---

## 🎨 11 Styles

| Style | Emoji | Description |
|-------|-------|-------------|
| Lightning | ⚡ | Black + blue lightning (KENSHIN signature) |
| Crimson | 🔴 | Dark maroon + white card overlay + rating badge |
| Campus | 🎓 | Dark bg, giant watermark, big title, character right |
| Ragnarok | ⚔️ | Blurred bg + frosted glass card + cover thumbnail |
| Arc | 🌑 | Dark + golden arc divider + big right-side title |
| Zenith | 🔵 | Navy hexagon bg + score circle badge |
| Neon | 💜 | Neon pink/purple glowing border |
| Frosted | ❄️ | B&W manga panel bg + frosted glass card |
| Minimal | ⬛ | Clean split, yellow accent line, blue buttons |
| Demon | 👹 | Dark atmospheric, red glow border, rating donut |
| Vertical | 📐 | Big art bg + crossword-style vertical title |

---

## 🤖 Commands

| Command | Action |
|---------|--------|
| `/start` | Welcome message |
| `/help` | Help & examples |
| `/thumb <name>` | Generate thumbnail |
| `/styles` | List all 11 styles |
| `/cancel` | Cancel session |

> Or just **send any name directly** — no command needed!

---

## 🚀 Quick Start (Local)

```bash
git clone https://github.com/yourusername/kenshin-anime-bot
cd kenshin-anime-bot
pip install -r requirements.txt
cp .env.example .env
# Edit .env → add your BOT_TOKEN
python bot.py
```

---

## 🚂 Deploy to Railway (GitHub)

### Step 1 — Create your bot
1. Open [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the **Bot Token**

### Step 2 — Push to GitHub
```bash
git init
git add .
git commit -m "🚀 Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/kenshin-anime-bot.git
git push -u origin main
```

### Step 3 — Deploy on Railway
1. Go to **[railway.app](https://railway.app)** → New Project
2. **Deploy from GitHub repo** → select your repo
3. Go to **Variables** tab → add:
   ```
   BOT_TOKEN = your_token_here
   ```
4. Railway builds + deploys automatically ✅

### Step 4 — Done!
Your bot is live 24/7 on Railway's free tier.

---

## 📁 Project Structure

```
kenshin-anime-bot/
├── bot.py               # Telegram bot + conversation flow
├── config.py            # Settings & style registry
├── requirements.txt
├── Dockerfile
├── railway.toml
├── .env.example
│
├── api/
│   ├── fetcher.py       # Jikan + AniList + Kitsu (parallel + cached)
│   └── __init__.py
│
├── generator/
│   ├── thumbnail.py     # Entry point
│   ├── styles.py        # All 11 styles (Pillow)
│   ├── utils.py         # Drawing helpers + fonts
│   └── __init__.py
│
└── assets/
    └── kenshin_logo.png # Your branding logo
```

---

## 🔧 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `CHANNEL_URL` | ❌ | Your channel link |
| `BOT_USERNAME` | ❌ | Bot username |
| `ALLOWED_USERS` | ❌ | Comma-separated user IDs (private mode) |

---

## 📦 APIs Used (all free, no key needed)

| API | What it gives |
|-----|---------------|
| [Jikan v4](https://docs.api.jikan.moe/) | MAL data — anime & manga |
| [AniList](https://anilist.gitbook.io/) | GraphQL — anime & manga |
| [Kitsu](https://kitsu.io/api/edge) | Extra images + manhwa |

All 3 are queried in parallel for maximum speed and coverage.

---

*Built with ❤️ for KENSHIN ANIME*
