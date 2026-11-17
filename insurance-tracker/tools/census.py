"""Census of the PDF corpus: page count, text-layer presence, detected insurer.

Writes data/census.csv and caches each PDF's text to data/text/<sha>.txt
Usage:  python tools/census.py "<pdf root folder>"
"""
import csv, hashlib, re, sys
from collections import Counter
from pathlib import Path

import pymupdf

INSURERS = {  # canonical name -> lowercase fingerprints
    "IFFCO-Tokio": ["iffco-tokio", "iffco tokio"],
    "Royal Sundaram": ["royal sundaram"],
    "ICICI Lombard": ["icici lombard"],
    "Bajaj Allianz": ["bajaj allianz", "bajaj general"],
    "TATA AIG": ["tata aig"],
    "HDFC ERGO": ["hdfc ergo"],
    "New India Assurance": ["new india assurance"],
    "United India": ["united india insurance"],
    "National Insurance": ["national insurance co"],
    "Oriental Insurance": ["oriental insurance"],
    "Go Digit": ["go digit", "digit general"],
    "SBI General": ["sbi general"],
    "Reliance General": ["reliance general"],
    "Shriram General": ["shriram general"],
    "Future Generali": ["future generali"],
    "Cholamandalam MS": ["cholamandalam"],
    "Kotak General": ["kotak mahindra general", "kotak general"],
    "Liberty General": ["liberty general"],
    "Magma HDI": ["magma hdi", "magma general"],
    "Universal Sompo": ["universal sompo"],
    "Zuno General": ["zuno general", "edelweiss general"],
    "Acko": ["acko general"],
    "Navi General": ["navi general"],
    "Raheja QBE": ["raheja qbe"],
}


def detect_insurer(text: str) -> str:
    low = text.lower()
    hits = Counter()
    for name, keys in INSURERS.items():
        for k in keys:
            hits[name] += low.count(k)
    best, n = hits.most_common(1)[0]
    return best if n else "UNKNOWN"


def main(root: str):
    root = Path(root)
    out_dir = Path("data/text"); out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for pdf in sorted(root.rglob("*.pdf")):
        raw = pdf.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()[:16]
        try:
            doc = pymupdf.open(stream=raw, filetype="pdf")
            pages = [p.get_text("text") for p in doc]
        except Exception as e:  # corrupt file
            rows.append(dict(file=str(pdf.relative_to(root)), sha=sha, pages=0, chars=0,
                             scanned_pages=0, insurer=f"ERROR: {e}"))
            continue
        text = "\n\f\n".join(pages)
        (out_dir / f"{sha}.txt").write_text(text, encoding="utf-8")
        rows.append(dict(
            file=str(pdf.relative_to(root)), sha=sha, pages=len(pages), chars=len(text),
            scanned_pages=sum(1 for t in pages if len(t.strip()) < 50),
            insurer=detect_insurer(text),
        ))
    Path("data").mkdir(exist_ok=True)
    with open("data/census.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)

    print(f"PDFs: {len(rows)}   unique by hash: {len({r['sha'] for r in rows})}")
    print("Insurers:", Counter(r["insurer"] for r in rows).most_common())
    print("Fully scanned (no text):", sum(1 for r in rows if r["chars"] < 100))
    print("Files with some image-only pages:", sum(1 for r in rows if r["scanned_pages"]))
    print("Pages distribution:", Counter(r["pages"] for r in rows).most_common())
    print("Folders:", Counter(Path(r["file"]).parts[0] for r in rows).most_common())


if __name__ == "__main__":
    main(sys.argv[1])
