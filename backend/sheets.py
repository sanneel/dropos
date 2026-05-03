"""
Google Sheets export module.
Connects via gspread service account when credentials are configured.
Falls back to mock log export when credentials are missing.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

COLUMNS = [
    "id", "product_name", "sell_price_eur", "cost_eur", "margin_pct",
    "caption", "hashtags", "source", "category", "audience",
    "url", "stage", "approved_at", "posted_at",
]


class SheetsExporter:
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._sheet = None

    def _connect(self) -> bool:
        if self._sheet:
            return True
        try:
            import gspread
            gc = gspread.service_account(filename=self.credentials_path)
            self._sheet = gc.open_by_key(self.spreadsheet_id).sheet1
            log.info("Connected to Google Sheets: %s", self.spreadsheet_id)
            return True
        except Exception as e:
            log.warning("Google Sheets connection failed (mock mode): %s", e)
            return False

    def export(self, products: list) -> dict:
        if self.credentials_path and self.spreadsheet_id:
            return self._export_real(products)
        return self._export_mock(products)

    def _export_real(self, products: list) -> dict:
        if not self._connect():
            return self._export_mock(products)

        try:
            existing = self._sheet.get_all_values()
            if not existing:
                self._sheet.append_row(COLUMNS)

            rows = []
            for p in products:
                hashtags = p.get("hashtags") or []
                if isinstance(hashtags, list):
                    hashtags = " ".join(f"#{t}" for t in hashtags)
                row = []
                for col in COLUMNS:
                    val = p.get(col, "")
                    row.append(str(val) if val is not None else "")
                rows.append(row)

            for row in rows:
                self._sheet.append_row(row)

            log.info("Exported %d products to Google Sheets", len(products))
            return {"ok": True, "exported": len(products), "mock": False}
        except Exception as e:
            log.error("Sheets export error: %s", e)
            return {"ok": False, "error": str(e)}

    def _export_mock(self, products: list) -> dict:
        log.info("Google Sheets mock export: %d products", len(products))
        for p in products:
            log.info(
                "  [SHEETS] %s | €%s | %s%% margin | stage=%s",
                p.get("product_name") or p.get("title", "?"),
                p.get("sell_price_eur", "?"),
                p.get("margin_pct", "?"),
                p.get("stage", "?"),
            )
        return {"ok": True, "exported": len(products), "mock": True}


_exporter = SheetsExporter()


def configure(credentials_path: str, spreadsheet_id: str) -> None:
    global _exporter
    _exporter = SheetsExporter(credentials_path, spreadsheet_id)


def export(products: list) -> dict:
    return _exporter.export(products)
