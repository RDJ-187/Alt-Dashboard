from __future__ import annotations

from collections import defaultdict
from typing import Any


class Extraction:
    """Primary field values plus independent second readings used for cross-checks."""

    def __init__(self, insurer: str):
        self.fields: dict[str, Any] = {"insurer": insurer}
        self.alts: dict[str, list[tuple[str, Any]]] = defaultdict(list)
        self.notes: list[str] = []

    def set(self, key: str, value: Any) -> None:
        if value not in (None, "", []):
            self.fields[key] = value

    def alt(self, key: str, source: str, value: Any) -> None:
        if value not in (None, "", []):
            self.alts[key].append((source, value))

    def get(self, key: str) -> Any:
        return self.fields.get(key)
