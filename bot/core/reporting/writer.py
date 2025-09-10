import csv
import json
import os
import threading
from typing import Iterable

from .ledger import TradeLedgerRow


class TradeLedgerWriter:
    def __init__(self, run_id: str, base_dir: str):
        self.run_id = run_id
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self._csv_path = os.path.join(base_dir, "trades.csv")
        self._jsonl_path = os.path.join(base_dir, "trades.jsonl")
        self._csv_lock = threading.Lock()
        self._json_lock = threading.Lock()
        self._ensure_csv_header()

    def _ensure_csv_header(self):
        header = TradeLedgerRow.csv_header_order()
        # (Re)write header only if file absent or empty
        if not os.path.exists(self._csv_path) or os.path.getsize(self._csv_path) == 0:
            with self._csv_lock, open(self._csv_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=header)
                w.writeheader()

    def append(self, row: TradeLedgerRow, formats: Iterable[str] = ("csv", "jsonl")):
        data = row.to_dict()
        if "csv" in formats:
            with self._csv_lock, open(self._csv_path, "a", newline="") as f:
                w = csv.DictWriter(f, fieldnames=TradeLedgerRow.csv_header_order())
                w.writerow(data)
        if "jsonl" in formats:
            line = json.dumps(data, separators=(",", ":"))
            with self._json_lock, open(self._jsonl_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

