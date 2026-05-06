"""2×3 product collage generator. Requires Pillow>=10.0.0."""
import asyncio, io, logging
from typing import Optional
import httpx

log = logging.getLogger(__name__)
CELL_SIZE, COLS, ROWS, GAP = 600, 2, 3, 6
BG = (248, 248, 248)

async def _fetch(url: str) -> Optional[bytes]:
    if not url: return None
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://www.1688.com/"})
        return r.content if r.status_code == 200 else None
    except Exception as e:
        log.warning("Collage fetch failed %s: %s", url[:80], e)
        return None

async def create_collage(image_urls: list[str]) -> Optional[bytes]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log.error("Pillow not installed"); return None
    raw = await asyncio.gather(*[_fetch(u) for u in image_urls[:COLS*ROWS]])
    blank = Image.new("RGB", (CELL_SIZE, CELL_SIZE), (210, 210, 210))
    cells = []
    for data in raw:
        if data:
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
                cells.append(ImageOps.fit(img, (CELL_SIZE, CELL_SIZE), Image.LANCZOS))
                continue
            except Exception: pass
        cells.append(blank.copy())
    while len(cells) < COLS * ROWS:
        cells.append(blank.copy())
    W = COLS * CELL_SIZE + (COLS - 1) * GAP
    H = ROWS * CELL_SIZE + (ROWS - 1) * GAP
    canvas = Image.new("RGB", (W, H), BG)
    for i, cell in enumerate(cells[:COLS*ROWS]):
        row, col = divmod(i, COLS)
        canvas.paste(cell, (col*(CELL_SIZE+GAP), row*(CELL_SIZE+GAP)))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90, optimize=True)
    log.info("Collage %dx%d %dKB", W, H, len(buf.getvalue())//1024)
    return buf.getvalue()
