"""
2×3 product collage generator. Requires Pillow>=10.0.0.

Memory-safety note: every PIL.Image object is explicitly closed via context
managers or .close() calls after its pixels have been composited onto the
canvas, preventing accumulation across large scrape batches.
"""
import asyncio, io, logging
from typing import Optional
import httpx

log = logging.getLogger(__name__)
CELL_SIZE, COLS, ROWS, GAP = 600, 2, 3, 6
BG = (248, 248, 248)

async def _fetch(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.1688.com/"})
        return r.content if r.status_code == 200 else None
    except Exception as e:
        log.warning("Collage fetch failed %s: %s", url[:80], e)
        return None


async def create_collage(image_urls: list[str]) -> Optional[bytes]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log.error("Pillow not installed")
        return None

    raw = await asyncio.gather(*[_fetch(u) for u in image_urls[:COLS * ROWS]])

    # ── Build cells, explicitly closing each source image after use ─────────────
    cells: list = []
    for data in raw:
        if data:
            try:
                # Use context manager so the source image is closed even if
                # ImageOps.fit raises an exception for a corrupted file.
                with Image.open(io.BytesIO(data)) as src:
                    rgb = src.convert("RGB")
                # ImageOps.fit returns a *new* image; close the intermediate rgb
                cell = ImageOps.fit(rgb, (CELL_SIZE, CELL_SIZE), Image.LANCZOS)
                rgb.close()
                cells.append(cell)
                continue
            except Exception as exc:
                log.debug("Collage cell decode failed: %s", exc)

        # Placeholder for missing or corrupt images — a solid grey tile
        cells.append(Image.new("RGB", (CELL_SIZE, CELL_SIZE), (210, 210, 210)))

    # Pad to a full 2×3 grid so the canvas math is always consistent
    while len(cells) < COLS * ROWS:
        cells.append(Image.new("RGB", (CELL_SIZE, CELL_SIZE), (210, 210, 210)))

    # ── Composite onto canvas ───────────────────────────────────────────────────
    W = COLS * CELL_SIZE + (COLS - 1) * GAP
    H = ROWS * CELL_SIZE + (ROWS - 1) * GAP
    canvas = Image.new("RGB", (W, H), BG)

    for i, cell in enumerate(cells[:COLS * ROWS]):
        row, col = divmod(i, COLS)
        canvas.paste(cell, (col * (CELL_SIZE + GAP), row * (CELL_SIZE + GAP)))
        cell.close()  # Release cell memory immediately after paste

    # ── Encode and release canvas ───────────────────────────────────────────────
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90, optimize=True)
    canvas.close()

    result = buf.getvalue()
    log.info("Collage %dx%d %dKB (%d cells)", W, H, len(result) // 1024, len(image_urls))
    return result
