"""
Adaptive product collage generator (up to 2×3). Requires Pillow>=10.0.0.

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
    """
    Build a grid collage (max 6 images). The grid adapts to the number of
    images so short batches / small collage posts do not get grey padding:
    1 → 1×1, 2 → 2×1, 3–4 → 2×2, 5–6 → 2×3. Cells are numbered left-to-right,
    top-to-bottom, matching the product_index order the AI prompt uses.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log.error("Pillow not installed")
        return None

    urls = [u for u in image_urls[:COLS * ROWS]]
    n = max(1, len(urls))
    cols = 1 if n == 1 else COLS
    rows = max(1, -(-n // cols))  # ceil

    raw = await asyncio.gather(*[_fetch(u) for u in urls])

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

    # Pad the last row so the canvas math is always consistent
    while len(cells) < cols * rows:
        cells.append(Image.new("RGB", (CELL_SIZE, CELL_SIZE), (210, 210, 210)))

    # ── Composite onto canvas ───────────────────────────────────────────────────
    W = cols * CELL_SIZE + (cols - 1) * GAP
    H = rows * CELL_SIZE + (rows - 1) * GAP
    canvas = Image.new("RGB", (W, H), BG)

    for i, cell in enumerate(cells[:cols * rows]):
        row, col = divmod(i, cols)
        canvas.paste(cell, (col * (CELL_SIZE + GAP), row * (CELL_SIZE + GAP)))
        cell.close()  # Release cell memory immediately after paste

    # ── Encode and release canvas ───────────────────────────────────────────────
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90, optimize=True)
    canvas.close()

    result = buf.getvalue()
    log.info("Collage %dx%d %dKB (%d cells)", W, H, len(result) // 1024, len(image_urls))
    return result
