"""
Multi-API fetcher: Jikan (MAL) + AniList + Kitsu — runs in parallel.
Results are cached in-memory for 30 minutes to avoid repeated hits.
"""

import asyncio
import logging
import re
from typing import Optional
import aiohttp
from cachetools import TTLCache

logger = logging.getLogger(__name__)

JIKAN_BASE   = "https://api.jikan.moe/v4"
ANILIST_BASE = "https://graphql.anilist.co"
KITSU_BASE   = "https://kitsu.io/api/edge"

# 30-min TTL, max 512 cached queries
_cache: TTLCache = TTLCache(maxsize=512, ttl=1800)

TIMEOUT = aiohttp.ClientTimeout(total=12)

# ── helpers ───────────────────────────────────────────────────────────────────

def _clean(text: str, max_len: int = 500) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\(Source:.*?\)", "", text)
    text = re.sub(r"\[Written by.*?\]", "", text)
    return text.strip()[:max_len]


def _build(
    title: str,
    title_orig: str = "",
    synopsis: str = "",
    score: Optional[float] = None,
    year: Optional[int] = None,
    genres: Optional[list] = None,
    image_url: str = "",
    banner_url: str = "",
    status: str = "",
    episodes: Optional[int] = None,
    media_type: str = "anime",
    fmt: str = "",
    source: str = "",
    **_,
) -> dict:
    return {
        "title":       title or "Unknown",
        "title_orig":  title_orig,
        "synopsis":    _clean(synopsis),
        "score":       score,
        "year":        year,
        "genres":      (genres or [])[:5],
        "image_url":   image_url,
        "banner_url":  banner_url,
        "status":      status,
        "episodes":    episodes,
        "type":        media_type,
        "format":      fmt,
        "source":      source,
    }


# ── Jikan ─────────────────────────────────────────────────────────────────────

async def _jikan(session: aiohttp.ClientSession, q: str, mtype: str) -> list[dict]:
    ep = "anime" if mtype == "anime" else "manga"
    url = f"{JIKAN_BASE}/{ep}?q={q}&limit=6&sfw=true"
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return []
            data = await r.json()
            out = []
            for it in data.get("data", [])[:6]:
                imgs = it.get("images", {}).get("jpg", {})
                aired = it.get("aired") or it.get("published") or {}
                yr = it.get("year") or (aired.get("prop", {}).get("from", {}).get("year"))
                out.append(_build(
                    title=it.get("title_english") or it.get("title"),
                    title_orig=it.get("title_japanese") or it.get("title"),
                    synopsis=it.get("synopsis", ""),
                    score=it.get("score"),
                    year=yr,
                    genres=[g["name"] for g in it.get("genres", [])] + [g["name"] for g in it.get("themes", [])],
                    image_url=imgs.get("large_image_url") or imgs.get("image_url"),
                    status=it.get("status", ""),
                    episodes=it.get("episodes") or it.get("chapters"),
                    media_type=mtype,
                    fmt=it.get("type", ""),
                    source="jikan",
                ))
            return out
    except Exception as e:
        logger.debug(f"Jikan error: {e}")
        return []


# ── AniList ───────────────────────────────────────────────────────────────────

_ANILIST_GQL = """
query ($s: String, $t: MediaType) {
  Page(perPage: 6) {
    media(search: $s, type: $t, sort: SEARCH_MATCH) {
      id title { romaji english native }
      description(asHtml: false)
      averageScore coverImage { extraLarge large }
      bannerImage genres startDate { year } status episodes chapters format
    }
  }
}
"""

async def _anilist(session: aiohttp.ClientSession, q: str, mtype: str) -> list[dict]:
    gtype = "ANIME" if mtype == "anime" else "MANGA"
    try:
        async with session.post(
            ANILIST_BASE,
            json={"query": _ANILIST_GQL, "variables": {"s": q, "t": gtype}},
        ) as r:
            if r.status != 200:
                return []
            data = await r.json()
            items = data.get("data", {}).get("Page", {}).get("media", [])
            out = []
            for it in items:
                t = it.get("title", {})
                sc = it.get("averageScore")
                cov = it.get("coverImage", {})
                out.append(_build(
                    title=t.get("english") or t.get("romaji"),
                    title_orig=t.get("native"),
                    synopsis=it.get("description", ""),
                    score=sc / 10 if sc else None,
                    year=it.get("startDate", {}).get("year"),
                    genres=it.get("genres", []),
                    image_url=cov.get("extraLarge") or cov.get("large"),
                    banner_url=it.get("bannerImage") or "",
                    status=it.get("status", ""),
                    episodes=it.get("episodes") or it.get("chapters"),
                    media_type=mtype,
                    fmt=it.get("format", ""),
                    source="anilist",
                ))
            return out
    except Exception as e:
        logger.debug(f"AniList error: {e}")
        return []


# ── Kitsu (bonus — good for manhwa / extra images) ────────────────────────────

async def _kitsu(session: aiohttp.ClientSession, q: str, mtype: str) -> list[dict]:
    ep = "anime" if mtype == "anime" else "manga"
    url = f"{KITSU_BASE}/{ep}?filter[text]={q}&page[limit]=4"
    try:
        async with session.get(url, headers={"Accept": "application/vnd.api+json"}) as r:
            if r.status != 200:
                return []
            data = await r.json()
            out = []
            for it in data.get("data", []):
                a = it.get("attributes", {})
                titles = a.get("titles", {})
                title = titles.get("en") or titles.get("en_jp") or a.get("canonicalTitle", "")
                imgs = a.get("posterImage", {})
                img = imgs.get("large") or imgs.get("medium") or imgs.get("original", "")
                banner = (a.get("coverImage") or {}).get("large", "")
                try:
                    sc = float(a.get("averageRating") or 0) / 10
                except Exception:
                    sc = None
                yr_str = (a.get("startDate") or "")[:4]
                yr = int(yr_str) if yr_str.isdigit() else None
                cats = a.get("categories", {}).get("data", [])
                out.append(_build(
                    title=title,
                    synopsis=a.get("synopsis", ""),
                    score=sc if sc else None,
                    year=yr,
                    genres=[],
                    image_url=img,
                    banner_url=banner,
                    status=a.get("status", ""),
                    episodes=a.get("episodeCount") or a.get("chapterCount"),
                    media_type=mtype,
                    fmt=a.get("showType") or a.get("mangaType", ""),
                    source="kitsu",
                ))
            return out
    except Exception as e:
        logger.debug(f"Kitsu error: {e}")
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def search_media(query: str, media_type: str = "anime") -> list[dict]:
    """
    Search all 3 APIs in parallel, deduplicate, return up to 6 results.
    Results are cached for 30 minutes.
    """
    cache_key = f"{media_type}::{query.lower().strip()}"
    if cache_key in _cache:
        return _cache[cache_key]

    connector = aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector, timeout=TIMEOUT) as session:
        tasks = [
            _jikan(session, query, media_type),
            _anilist(session, query, media_type),
            _kitsu(session, query, media_type),
        ]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set[str] = set()
    merged: list[dict] = []
    for batch in raw:
        if not isinstance(batch, list):
            continue
        for item in batch:
            key = (item.get("title") or "").lower().strip()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)

    result = merged[:6]
    _cache[cache_key] = result
    return result


async def download_image(url: str) -> Optional[bytes]:
    """Download image bytes; returns None on failure."""
    if not url:
        return None
    try:
        connector = aiohttp.TCPConnector(limit=10)
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as session:
            async with session.get(url) as r:
                if r.status == 200:
                    return await r.read()
    except Exception as e:
        logger.debug(f"Image DL error {url}: {e}")
    return None
