"""Result log (spec 6.7): one record per evaluation, keyed by session_id + input_id.

LOG_DESTINATION supports:
  local:<path>  - append-only JSON Lines file (default, used for local dev/testing)
  table:<...>   - Azure Table Storage (spec 6.1 proposed target)

Azure Table Storage is not wired up yet: no Azure resource has been
provisioned in this environment. `local:` is the only destination exercised
in tests; `table:` raises NotImplementedError with a clear message so a
misconfiguration fails loudly instead of silently dropping records.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


class ResultLog:
    def __init__(self, destination: str):
        self.destination = destination

    def write(self, record: Dict[str, Any]) -> None:
        if self.destination.startswith("local:"):
            self._write_local(self.destination[len("local:") :], record)
        elif self.destination.startswith("table:"):
            raise NotImplementedError(
                "Azure Table Storage result log is not implemented yet — no Azure "
                "storage account has been provisioned for this POC. Use a "
                "'local:<path>' LOG_DESTINATION until that's decided (spec 6.1)."
            )
        else:
            raise ValueError(f"Unrecognized LOG_DESTINATION: {self.destination!r}")

    @staticmethod
    def _write_local(path_str: str, record: Dict[str, Any]) -> None:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, default=str) + "\n"
        with _write_lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
