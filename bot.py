"""
⚡ KENSHIN ANIME Thumbnail Bot
Fast. Powerful. Branded. MongoDB-backed.
"""

import io
import logging
import asyncio
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters,
)
from telegram.constants import ParseMode

from config import BOT_TOKEN, CHANNEL_URL, STYLES, ADMIN_IDS, MONGO_URI
from api import search_media, download_image
from generator import generate_thumbnail, STYLE_FUNCS
from database import init_db, log_thumbnail, get_user_stats, get_global_stats, close_db

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── States ────────────────────────────────────────────────────────────────────
S_TYPE, S_RESULT, S_STYLE = range(3)
P_TYPE, P_RESULT, P_STYLE, P_BACK = "T:", "R:", "S:", "BACK"

# ── Keyboards ─────────────────────────────────────────────────────────────────
def _kbd_type(query: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎬 Anime",  callback_data=f"{P_TYPE}anime:{query}"),
        InlineKeyboardButton("📕 Manga",  callback_data=f"{P_TYPE}manga:{query}"),
        InlineKeyboardButton("📗 Manhwa", callback_data=f"{P_TYPE}manhwa:{query}"),
    ]])

def _kbd_results(results: list) -> InlineKeyboardMarkup:
    src_icon = {"jikan": "📘", "anilist": "🅰️", "kitsu": "🐱"}
    rows = []
    for i, r in enumerate(results[:6]):
        title = (r.get("title") or f"Result {i+1}")[:36]
        icon  = src_icon.get(r.get("source",""), "📌")
        rows.append([InlineKeyboardButton(f"{i+1}. {icon} {title}",
                                          callback_data=f"{P_RESULT}{i}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=P_BACK)])
    return InlineKeyboardMarkup(rows)

def _kbd_styles(current: str = "") -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, m in STYLES.items():
        label = f"✅{m['emoji']}{m['name']}" if key == current else f"{m['emoji']} {m['name']}"
        row.append(InlineKeyboardButton(label, callback_data=f"{P_STYLE}{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Back to results", callback_data=P_BACK)])
    return InlineKeyboardMarkup(rows)

def _fmt_info(item: dict) -> str:
    sc   = f"⭐ {float(item['score']):.1f}/10" if item.get("score") else "⭐ N/A"
    year = str(item.get("year") or "—")
    gens = ", ".join(item.get("genres", [])[:3]) or "—"
    return f"*{item.get('title','?')}*\n📅 {year}  |  {sc}\n🏷️ {gens}"

# ── Welcome text ──────────────────────────────────────────────────────────────
WELCOME = """
⚡ *KENSHIN ANIME Thumbnail Bot* 🎌

Generate **broadcast-ready** 1280×720 thumbnails for your channel!

━━━━━━━━━━━━━━━━━━━━
*How to use:*
Just send any name — I'll do the rest!

*Examples:*
`Solo Leveling`
`Berserk manga`
`Chainsaw Man`
`Greatest Estate Developer manhwa`
`Attack on Titan`

━━━━━━━━━━━━━━━━━━━━
*Commands:*
/thumb `<name>` — Generate thumbnail
/styles — See all 11 styles
/mystats — Your usage stats
/help — Show this message
/cancel — Cancel session

━━━━━━━━━━━━━━━━━━━━
*11 Styles:* ⚡🔴🎓⚔️🌑🔵💜❄️⬛👹📐

All thumbnails stamped with KENSHIN ANIME branding!
"""

STYLES_MSG = "*🎨 11 Thumbnail Styles:*\n\n" + "\n".join(
    f"{m['emoji']} *{m['name']}* — {m['desc']}"
    for m in STYLES.values()
)

# ── Commands ──────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.MARKDOWN)

async def cmd_styles(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(STYLES_MSG, parse_mode=ParseMode.MARKDOWN)

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    await update.message.reply_text("✅ Cancelled! Send a name to start fresh.")
    return ConversationHandler.END

async def cmd_mystats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    data = await get_user_stats(uid)
    if not data:
        await update.message.reply_text(
            "📊 No stats yet! Generate some thumbnails first 😎",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    total = data.get("total_thumbs", 0)
    joined = data.get("joined", "—")
    await update.message.reply_text(
        f"📊 *Your Stats:*\n\n"
        f"🖼 Thumbnails generated: *{total}*\n"
        f"📅 First used: `{str(joined)[:10]}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin-only global stats."""
    uid = update.effective_user.id
    if ADMIN_IDS and uid not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    data = await get_global_stats()
    if not data:
        await update.message.reply_text("📊 No database connected.")
        return
    await update.message.reply_text(
        f"📊 *Bot Stats:*\n\n"
        f"👥 Total users: *{data.get('total_users', 0)}*\n"
        f"🖼 Thumbnails made: *{data.get('total_thumbs', 0)}*\n"
        f"🏆 Top style: *{data.get('top_style', '—')}*\n"
        f"🔥 Top title: *{data.get('top_title', '—')}*",
        parse_mode=ParseMode.MARKDOWN
    )

# ── Conversation entry ────────────────────────────────────────────────────────
async def _ask_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE, query: str) -> int:
    ctx.user_data["query"] = query
    await update.message.reply_text(
        f"🔍 *{query}*\n\nWhat type?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_kbd_type(query),
    )
    return S_TYPE

async def cmd_thumb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = " ".join(ctx.args) if ctx.args else ""
    if not q:
        await update.message.reply_text(
            "Example: `/thumb Solo Leveling`", parse_mode=ParseMode.MARKDOWN)
        return ConversationHandler.END
    return await _ask_type(update, ctx, q)

async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.message.text.strip()
    if not q or q.startswith("/"):
        return ConversationHandler.END
    return await _ask_type(update, ctx, q)

# ── Type → search ─────────────────────────────────────────────────────────────
async def on_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    cb = update.callback_query
    await cb.answer()
    data  = cb.data[len(P_TYPE):]
    mtype, _, query = data.partition(":")
    ctx.user_data.update({"mtype": mtype, "query": query})

    icons = {"anime": "🎬", "manga": "📕", "manhwa": "📗"}
    await cb.edit_message_text(
        f"{icons.get(mtype,'🔍')} Searching *{query}* …",
        parse_mode=ParseMode.MARKDOWN,
    )

    results = await search_media(query, mtype)
    if not results:
        await cb.edit_message_text(
            f"❌ No results for *{query}*\nTry different spelling.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    ctx.user_data["results"] = results
    await cb.edit_message_text(
        f"📋 *{len(results)} results* for *{query}*\nPick one:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_kbd_results(results),
    )
    return S_RESULT

# ── Result → style picker ─────────────────────────────────────────────────────
async def on_result(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    cb = update.callback_query
    await cb.answer()

    if cb.data == P_BACK:
        q = ctx.user_data.get("query", "")
        await cb.edit_message_text(
            f"🔍 *{q}*\n\nWhat type?",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_kbd_type(q),
        )
        return S_TYPE

    idx = int(cb.data[len(P_RESULT):])
    results = ctx.user_data.get("results", [])
    if idx >= len(results):
        await cb.answer("Invalid selection", show_alert=True)
        return S_RESULT

    selected = results[idx]
    ctx.user_data["selected"] = selected
    await cb.edit_message_text(
        f"✅ *Selected:*\n{_fmt_info(selected)}\n\n🎨 Choose a style:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_kbd_styles(),
    )
    return S_STYLE

# ── Style → generate ──────────────────────────────────────────────────────────
async def on_style(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    cb = update.callback_query

    if cb.data == P_BACK:
        await cb.answer()
        results = ctx.user_data.get("results", [])
        if not results:
            await cb.edit_message_text("Session expired. Send a name to start again.")
            return ConversationHandler.END
        await cb.edit_message_text(
            "📋 Pick a result:",
            reply_markup=_kbd_results(results),
        )
        return S_RESULT

    await cb.answer("⚡ Generating…")
    style = cb.data[len(P_STYLE):]
    selected = ctx.user_data.get("selected")
    if not selected:
        await cb.edit_message_text("Session expired. Send a name to start again.")
        return ConversationHandler.END

    sm = STYLES.get(style, {"emoji": "⚡", "name": style})
    await cb.edit_message_text(
        f"{sm['emoji']} Generating *{sm['name']}* for *{selected.get('title')}* …",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        # Download cover image
        cover_bytes: Optional[bytes] = None
        for url in [selected.get("image_url"), selected.get("banner_url")]:
            if url:
                cover_bytes = await download_image(url)
                if cover_bytes:
                    break

        # Generate in thread pool (non-blocking)
        loop = asyncio.get_event_loop()
        thumb = await loop.run_in_executor(
            None, generate_thumbnail, cover_bytes or b"", selected, style
        )

        # Build caption
        sc    = selected.get("score")
        sc_t  = f"⭐ {float(sc):.1f}/10" if sc else ""
        gens  = ", ".join(selected.get("genres", [])[:3])
        year  = str(selected.get("year") or "")
        mtype = (selected.get("type") or "anime").upper()

        caption = (
            f"⚡ *{selected.get('title')}*\n"
            f"{sm['emoji']} Style: *{sm['name']}*\n"
            f"📋 {mtype}"
            + (f"  •  📅 {year}" if year else "")
            + (f"  •  {sc_t}" if sc_t else "")
            + (f"\n🏷️ {gens}" if gens else "")
            + f"\n\n_Powered by @KenshinAnimeBot_"
        )

        await ctx.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=io.BytesIO(thumb),
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_kbd_styles(current=style),
        )

        await cb.edit_message_text(
            f"✅ Done! Tap another style below to switch look:",
            reply_markup=_kbd_styles(current=style),
        )

        # Log to MongoDB (fire and forget)
        user = update.effective_user
        asyncio.create_task(log_thumbnail(
            user_id=user.id,
            username=user.username or user.first_name or "",
            title=selected.get("title", ""),
            media_type=selected.get("type", "anime"),
            style=style,
        ))

    except Exception as e:
        logger.error(f"Generate error: {e}", exc_info=True)
        await cb.edit_message_text(
            f"❌ Error generating. Tap to retry:",
            reply_markup=_kbd_styles(current=style),
        )

    return S_STYLE

# ── Error handler ─────────────────────────────────────────────────────────────
async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception:", exc_info=ctx.error)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN not set!")

    app = Application.builder().token(BOT_TOKEN).build()

    # Init DB on startup
    async def _post_init(application: Application):
        await init_db(MONGO_URI)

    async def _post_shutdown(application: Application):
        await close_db()

    app.post_init     = _post_init
    app.post_shutdown = _post_shutdown

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("thumb", cmd_thumb),
            MessageHandler(filters.TEXT & ~filters.COMMAND, on_text),
        ],
        states={
            S_TYPE:   [CallbackQueryHandler(on_type,   pattern=f"^{P_TYPE}")],
            S_RESULT: [CallbackQueryHandler(on_result, pattern=f"^({P_RESULT}|{P_BACK})")],
            S_STYLE:  [CallbackQueryHandler(on_style,  pattern=f"^({P_STYLE}|{P_BACK})")],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("styles",  cmd_styles))
    app.add_handler(CommandHandler("mystats", cmd_mystats))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(conv)
    app.add_error_handler(on_error)

    logger.info("⚡ KENSHIN ANIME Bot running…")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
