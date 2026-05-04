"""
Google Sheets export module.
Connects via gspread service account when credentials are configured.
Falls back to mock log export when credentials are missing.
"""

import logging
import os
import json
from typing import Optional

log = logging.getLogger(__name__)

COLUMNS = [
    "id", "product_name", "sell_price_eur", "cost_eur", "margin_pct",
    "caption", "hashtags", "source", "category", "audience",
    "url", "stage", "approved_at", "posted_at",
]

SETTINGS_SHEET = "DropOS Settings"
PRODUCTS_SHEET = "DropOS Products"
EXPORT_SHEET = "DropOS Export"
SETTINGS_COLUMNS = ["key", "value_json"]
PRODUCT_COLUMNS = ["source_id", "data_json"]


class SheetsExporter:
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        spreadsheet_id: Optional[str] = None,
    ):
        self.credentials_path = credentials_path
        self.spreadsheet_id = spreadsheet_id
        self._sheet = None
        self._spreadsheet = None

    def _connect(self) -> bool:
        if self._spreadsheet:
            return True
        try:
            import gspread
            creds_file = self.credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if not creds_file:
                log.warning("Google Sheets credentials are not configured (mock mode)")
                return False
            gc = gspread.service_account(filename=creds_file)
            self._spreadsheet = gc.open_by_key(self.spreadsheet_id)
            self._sheet = self._spreadsheet.sheet1
            log.info("Connected to Google Sheets: %s", self.spreadsheet_id)
            return True
        except Exception as e:
            log.warning("Google Sheets connection failed (mock mode): %s", e)
            return False

    def _worksheet(self, title: str, columns: list[str]):
        if not self._connect():
            return None
        try:
            ws = self._spreadsheet.worksheet(title)
        except Exception:
            ws = self._spreadsheet.add_worksheet(title=title, rows=1000, cols=max(len(columns), 2))

        first_row = ws.row_values(1)
        if first_row != columns:
            ws.clear()
            ws.append_row(columns)
        return ws

    def export(self, products: list) -> dict:
        if (self.credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")) and self.spreadsheet_id:
            return self._export_real(products)
        return self._export_mock(products)

    def append_rows(self, data: list) -> dict:
        if not data:
            return {"ok": True, "exported": 0, "mock": False}
        if (self.credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")) and self.spreadsheet_id:
            return self._export_real(data)
        return self._export_mock(data)

    def _export_real(self, products: list) -> dict:
        if not self._connect():
            return self._export_mock(products)

        try:
            ws = self._worksheet(EXPORT_SHEET, COLUMNS)
            if not ws:
                return self._export_mock(products)

            rows = []
            for p in products:
                hashtags = p.get("hashtags") or []
                if isinstance(hashtags, list):
                    hashtags = " ".join(f"#{t}" for t in hashtags)
                row = []
                for col in COLUMNS:
                    val = p.get(col, "")
                    if col == "hashtags":
                        val = hashtags
                    row.append(str(val) if val is not None else "")
                rows.append(row)

            if rows:
                ws.append_rows(rows, value_input_option="RAW")

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

    def save_settings(self, settings: dict) -> dict:
        ws = self._worksheet(SETTINGS_SHEET, SETTINGS_COLUMNS)
        if not ws:
            return {"ok": False, "mock": True, "saved": 0}

        rows = [
            [key, json.dumps(value, ensure_ascii=False)]
            for key, value in sorted((settings or {}).items())
        ]
        ws.clear()
        ws.append_row(SETTINGS_COLUMNS)
        if rows:
            ws.append_rows(rows, value_input_option="RAW")
        return {"ok": True, "saved": len(rows), "mock": False}

    def load_settings(self) -> dict:
        ws = self._worksheet(SETTINGS_SHEET, SETTINGS_COLUMNS)
        if not ws:
            return {}

        settings = {}
        for row in ws.get_all_records():
            key = str(row.get("key", "")).strip()
            if not key:
                continue
            raw = row.get("value_json", "")
            try:
                settings[key] = json.loads(raw)
            except Exception:
                settings[key] = raw
        return settings

    def save_products(self, products: list) -> dict:
        ws = self._worksheet(PRODUCTS_SHEET, PRODUCT_COLUMNS)
        if not ws:
            return {"ok": False, "mock": True, "saved": 0}

        rows = []
        for product in products or []:
            source_id = str(product.get("source_id") or product.get("id") or "").strip()
            if not source_id:
                continue
            rows.append([source_id, json.dumps(product, ensure_ascii=False)])

        ws.clear()
        ws.append_row(PRODUCT_COLUMNS)
        if rows:
            ws.append_rows(rows, value_input_option="RAW")
        return {"ok": True, "saved": len(rows), "mock": False}

    def load_products(self) -> list:
        ws = self._worksheet(PRODUCTS_SHEET, PRODUCT_COLUMNS)
        if not ws:
            return []

        products = []
        for row in ws.get_all_records():
            raw = row.get("data_json", "")
            try:
                product = json.loads(raw)
            except Exception:
                continue
            if isinstance(product, dict):
                products.append(product)
        return products


_exporter = SheetsExporter()


def configure(credentials_path: str, spreadsheet_id: str) -> None:
    global _exporter
    _exporter = SheetsExporter(credentials_path, spreadsheet_id)


def export(products: list) -> dict:
    return _exporter.export(products)


def append_rows(data: list) -> dict:
    return _exporter.append_rows(data)


def save_settings(settings: dict) -> dict:
    return _exporter.save_settings(settings)


def load_settings() -> dict:
    return _exporter.load_settings()


def save_products(products: list) -> dict:
    return _exporter.save_products(products)


def load_products() -> list:
    return _exporter.load_products()


def verify_writable() -> bool:
    try:
        return _exporter._connect()
    except Exception:
        return False
