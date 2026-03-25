"""Main thumbnail entry point."""

import logging
from PIL import Image

from .utils import bytes_to_img, img_to_bytes, setup_fonts, W, H
from .styles import STYLE_FUNCS

logger = logging.getLogger(__name__)

# Pre-load fonts once at startup
setup_fonts()


def generate_thumbnail(cover_bytes: bytes, info: dict, style: str = "lightning") -> bytes:
    """
    Generate a 1280×720 JPEG thumbnail.

    Args:
        cover_bytes : raw image bytes (cover / poster)
        info        : media info dict (title, synopsis, score, genres, …)
        style       : one of STYLE_FUNCS keys

    Returns:
        JPEG bytes
    """
    cover = bytes_to_img(cover_bytes)
    if cover is None:
        cover = Image.new("RGBA", (400, 600), (35, 35, 55, 255))

    fn = STYLE_FUNCS.get(style) or STYLE_FUNCS["lightning"]

    try:
        result = fn(cover, info)
        return img_to_bytes(result)
    except Exception as e:
        logger.error(f"Style '{style}' failed: {e}", exc_info=True)
        try:
            return img_to_bytes(STYLE_FUNCS["lightning"](cover, info))
        except Exception as e2:
            logger.error(f"Fallback failed: {e2}", exc_info=True)
            # Return a plain placeholder
            placeholder = Image.new("RGB", (W, H), (20, 20, 30))
            return img_to_bytes(placeholder)
