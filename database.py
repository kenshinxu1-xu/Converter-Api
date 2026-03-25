"""
MongoDB async database layer using Motor.
Stores: user stats, thumbnail history, usage analytics.
Falls back gracefully if MONGO_URI is not set.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_db = None
_client = None


async def init_db(mongo_uri: str):
    """Initialize MongoDB connection."""
    global _db, _client
    if not mongo_uri:
        logger.warning("MONGO_URI not set — database features disabled.")
        return
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        _client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=5000)
        _db = _client["kenshin_anime_bot"]
        # Test connection
        await _client.admin.command("ping")
        logger.info("✅ MongoDB connected!")
    except Exception as e:
        logger.warning(f"MongoDB connection failed: {e} — running without DB.")
        _db = None


def _ready() -> bool:
    return _db is not None


# ── User stats ────────────────────────────────────────────────────────────────

async def log_thumbnail(user_id: int, username: str, title: str,
                        media_type: str, style: str):
    """Log every generated thumbnail."""
    if not _ready():
        return
    try:
        await _db.thumbnails.insert_one({
            "user_id":    user_id,
            "username":   username or "",
            "title":      title,
            "media_type": media_type,
            "style":      style,
            "created_at": datetime.utcnow(),
        })
        # Upsert user stats
        await _db.users.update_one(
            {"user_id": user_id},
            {
                "$set":  {"username": username or "", "last_seen": datetime.utcnow()},
                "$inc":  {"total_thumbs": 1},
                "$setOnInsert": {"joined": datetime.utcnow()},
            },
            upsert=True,
        )
    except Exception as e:
        logger.debug(f"DB log error: {e}")


async def get_user_stats(user_id: int) -> dict:
    """Get stats for a specific user."""
    if not _ready():
        return {}
    try:
        user = await _db.users.find_one({"user_id": user_id})
        return user or {}
    except Exception:
        return {}


async def get_global_stats() -> dict:
    """Get bot-wide stats (for admin)."""
    if not _ready():
        return {"db": "not connected"}
    try:
        total_users  = await _db.users.count_documents({})
        total_thumbs = await _db.thumbnails.count_documents({})
        # Most popular style
        pipeline = [
            {"$group": {"_id": "$style", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 1},
        ]
        top_style_cur = await _db.thumbnails.aggregate(pipeline).to_list(1)
        top_style = top_style_cur[0]["_id"] if top_style_cur else "—"
        # Most popular title
        pipeline2 = [
            {"$group": {"_id": "$title", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 1},
        ]
        top_title_cur = await _db.thumbnails.aggregate(pipeline2).to_list(1)
        top_title = top_title_cur[0]["_id"] if top_title_cur else "—"
        return {
            "total_users":  total_users,
            "total_thumbs": total_thumbs,
            "top_style":    top_style,
            "top_title":    top_title,
        }
    except Exception as e:
        logger.debug(f"Stats error: {e}")
        return {}


async def close_db():
    """Close MongoDB connection cleanly."""
    global _client
    if _client:
        _client.close()
