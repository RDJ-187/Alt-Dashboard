"""PDF loading with layout awareness.

Every text line keeps its page and bounding box, so values can be located by their
position relative to a label (right of it / below it), not just by reading order.
Rotated or vertical text (watermarks) is dropped: on the Go Digit forms such text
otherwise bleeds into table cells and corrupts values like the chassis number.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .common import clean


@dataclass
class Line:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


def _v_overlap(a: Line, b: Line) -> float:
    inter = min(a.y1, b.y1) - max(a.y0, b.y0)
    return inter / max(1e-6, min(a.y1 - a.y0, b.y1 - b.y0))


def _h_overlap(a: Line, b: Line, pad: float) -> bool:
    return b.x0 <= a.x1 + pad and b.x1 >= a.x0 - pad


class PdfDoc:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = self.path.read_bytes()
        self.sha256 = hashlib.sha256(data).hexdigest()
        doc = pymupdf.open(stream=data, filetype="pdf")
        self.n_pages = len(doc)
        self.lines: list[Line] = []
        self.page_texts: list[str] = []
        for pno, page in enumerate(doc):
            plines = []
            for block in page.get_text("dict")["blocks"]:
                for l in block.get("lines", []):
                    dx, dy = l["dir"]
                    if dx < 0.99:  # rotated / vertical watermark text
                        continue
                    text = re.sub(r"\s+", " ", "".join(s["text"] for s in l["spans"])).strip()
                    if text:
                        plines.append(Line(pno, *l["bbox"], text))
            self.lines += plines
            self.page_texts.append("\n".join(x.text for x in plines))
        self.text = "\n".join(self.page_texts)

    # ---------- text helpers ----------
    def find(self, pattern: str, text: str | None = None, group: int = 1, flags=re.I) -> str | None:
        m = re.search(pattern, self.text if text is None else text, flags)
        return clean(m.group(group)) if m else None

    def page(self, i: int) -> str:
        return self.page_texts[i] if i < self.n_pages else ""

    # ---------- layout helpers ----------
    def labels(self, label: str, page: int | None = None) -> list[Line]:
        rx = re.compile(label, re.I)
        return [l for l in self.lines if (page is None or l.page == page) and rx.fullmatch(l.text)]

    def right_of(self, label: str, page: int | None = None, max_dx: float = 380) -> str | None:
        """Text of the nearest line on the same row, to the right of the label."""
        for lab in self.labels(label, page):
            cands = [
                l for l in self.lines
                if l.page == lab.page and l is not lab and l.text not in (":", "-:")
                and l.x0 >= lab.x1 - 2 and l.x0 - lab.x1 <= max_dx and _v_overlap(lab, l) > 0.5
            ]
            if cands:
                return clean(min(cands, key=lambda l: l.x0).text.lstrip(": "))
        return None

    def below(self, label: str, page: int | None = None, max_dy: float = 30, pad: float = 6,
              n: int = 1, joiner: str = " ", gap: float = 3.5) -> str | None:
        """Text of the cell directly beneath the label's column.

        Takes the nearest line below, then continues with lines that follow it with a
        vertical gap <= `gap` (a wrapped cell), up to n lines. A bigger gap means the
        next table row, which is never merged in.
        """
        for lab in self.labels(label, page):
            cands = sorted(
                (l for l in self.lines
                 if l.page == lab.page and l is not lab and l.y0 >= lab.y1 - 1
                 and l.y0 - lab.y1 <= max_dy and _h_overlap(lab, l, pad)),
                # same row -> prefer the line that overlaps the label column the most
                key=lambda l: (round(l.y0), -(min(l.x1, lab.x1) - max(l.x0, lab.x0))),
            )
            if not cands:
                continue
            cell = [cands[0]]
            for l in cands[1:]:
                if len(cell) >= n or l.y0 - cell[-1].y1 > gap:
                    break
                cell.append(l)
            return clean(joiner.join(l.text for l in cell))
        return None

    def continued(self, line_regex: str, page: int | None = None, gap: float = 2.0) -> str | None:
        """Text after the match on its line plus any wrapped continuation lines aligned under it."""
        rx = re.compile(line_regex, re.I)
        for i, l in enumerate(self.lines):
            if (page is not None and l.page != page) or not rx.search(l.text):
                continue
            parts = [rx.split(l.text, maxsplit=1)[-1]]
            prev = l
            for nxt in self.lines[i + 1:i + 4]:
                if nxt.page == l.page and abs(nxt.x0 - l.x0) < 3 and -3 <= nxt.y0 - prev.y1 <= gap \
                        and re.fullmatch(r"[A-Z0-9 .,&()-]+", nxt.text):
                    parts.append(nxt.text)
                    prev = nxt
                else:
                    break
            return clean(" ".join(p for p in parts if p))
        return None

    def grid_value(self, page: int, header: str, joiner: str = "") -> str | None:
        """Independent second engine: pdfplumber ruled-table detection.

        Finds the table cell whose text matches `header` and returns the cell at the same
        column in the next row. Used only as a cross-check source (it mis-reads tables
        that carry rotated watermarks, which PyMuPDF filters out).
        """
        if not hasattr(self, "_grids"):
            self._grids = {}
        if page not in self._grids:
            import pdfplumber
            with pdfplumber.open(self.path) as pdf:
                self._grids[page] = pdf.pages[page].extract_tables() if page < len(pdf.pages) else []
        rx = re.compile(header, re.I)
        for table in self._grids[page]:
            for r, row in enumerate(table[:-1]):
                for c, cell in enumerate(row):
                    if cell and rx.fullmatch(re.sub(r"\s+", " ", cell).strip()):
                        val = table[r + 1][c] if c < len(table[r + 1]) else None
                        return clean(joiner.join((val or "").split("\n")))
        return None

    def row_text(self, page: int, tol: float = 3.0) -> str:
        """Page rebuilt as visual rows: lines sharing a baseline joined left-to-right with ' | '.

        Table headers and their values then appear as aligned rows instead of the
        scrambled reading order — this is what the LLM is shown.
        """
        lines = sorted((l for l in self.lines if l.page == page), key=lambda l: ((l.y0 + l.y1) / 2, l.x0))
        rows: list[list[Line]] = []
        for l in lines:
            mid = (l.y0 + l.y1) / 2
            if rows and abs(mid - (rows[-1][0].y0 + rows[-1][0].y1) / 2) <= tol:
                rows[-1].append(l)
            else:
                rows.append([l])
        return "\n".join(" | ".join(x.text for x in sorted(r, key=lambda x: x.x0)) for r in rows)

    def page_with(self, needle: str, default: int = 0) -> int:
        for i, t in enumerate(self.page_texts):
            if needle in t:
                return i
        return default
