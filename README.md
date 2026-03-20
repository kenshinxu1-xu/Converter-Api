# KENSHIN ANIME Bot 🎌

Official Telegram bot for KENSHIN ANIME channel.

## Features
- 🔍 Search Anime, Manga, Manhwa, Manhua
- 📝 Auto-generate Telegram captions (with AI)
- 🖼 Generate 3 styles of thumbnails (Weebs, Kenshin, Campus)
- 📊 Full anime info with poster
- 🔥 Top airing anime list
- Inline buttons for easy navigation

## Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Show all commands |
| `/anime <name>` | Search anime |
| `/manga <name>` | Search manga |
| `/manhwa <name>` | Search manhwa (Korean) |
| `/manhua <name>` | Search manhua (Chinese) |
| `/caption <name>` | Get Telegram caption |
| `/thumbnail <name>` | Weebs style thumbnail |
| `/thumb2 <name>` | Kenshin style thumbnail |
| `/thumb3 <name>` | Campus style thumbnail |
| `/info <name>` | Full anime info |
| `/top` | Top airing anime |

---

## 🚀 Deploy on Railway (Free)

### Step 1: Get Bot Token
1. Open Telegram → search `@BotFather`
2. Send `/newbot`
3. Give it a name: `KENSHIN ANIME Bot`
4. Give it a username: `kenshinanimebot` (unique)
5. Copy the **API token** it gives you

### Step 2: Upload to GitHub
1. Go to [github.com](https://github.com) → New repository
2. Name it `kenshin-anime-bot`
3. Upload these files:
   - `bot.py`
   - `requirements.txt`
   - `Procfile`
   - `railway.toml`
   - `README.md`

### Step 3: Deploy on Railway
1. Go to [railway.app](https://railway.app)
2. Sign in with GitHub
3. Click **New Project** → **Deploy from GitHub repo**
4. Select `kenshin-anime-bot`
5. Click **Add Variables** and set:
   ```
   BOT_TOKEN = your_bot_token_here
   ANTHROPIC_KEY = your_claude_api_key (optional, for AI captions)
   ```
6. Click **Deploy** ✅

### Step 4: Test your bot
Open Telegram → search your bot → send `/start`

---

## Optional: Claude AI Captions
To enable AI-powered captions:
1. Get API key from [console.anthropic.com](https://console.anthropic.com)
2. Add to Railway: `ANTHROPIC_KEY = sk-ant-...`

Without it, the bot still works with the template caption format.

---

## APIs Used
- **Jikan API** — Unofficial MyAnimeList (free, no key needed)
- **MangaDex API** — Manhwa/Manhua (free, no key needed)
- **images.weserv.nl** — Image proxy (free)
- **Anthropic Claude** — AI captions (optional, paid)

---

Made with ❤️ for **KENSHIN ANIME** channel
