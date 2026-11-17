# Vehicle Insurance Tracker — Extraction Engine

Turns motor-insurance PDFs (Royal Sundaram, ICICI Lombard, IFFCO-Tokio, Go Digit) into one
verified SQLite table that feeds the dashboard and expiry alerts.

## How accuracy is guaranteed

No value is trusted from a single reading. Every record passes through four independent checks:

```
PDF ─► PyMuPDF (layout-aware, rotated watermark text removed)
        │
        ├─► Stage 1  RULES      per-insurer parser reads each value by its label position
        │                       + second readings from elsewhere in the same PDF
        │                         (cover letter vs schedule, footer line, invoice page)
        │                       + pdfplumber table engine as an independent cross-check (ICICI)
        │                       + file name (registration / chassis) cross-check
        │
        ├─► Stage 2  LLM        local Qwen2.5-7B (Ollama, CPU) fills a strict JSON schema
        │                       every LLM value must literally exist in the PDF ("grounded")
        │
        ├─► Stage 3  RECONCILE  rules vs LLM per field: agree / conflict / rules_only / llm_only
        │
        └─► VALIDATE            required fields, date logic, 17-char chassis, premium maths
                                (OD + TP ≤ total ≤ (OD + TP) × 1.18 GST), folder-label check
                                ─► status = verified | review
```

## Run

```bash
# one-time setup (Windows Anaconda python)
python -m venv .venv
.venv\Scripts\python -m pip install pymupdf pdfplumber pydantic pyyaml requests openpyxl
ollama pull qwen2.5:7b-instruct

# rules + validation for all PDFs  (≈20 s for 400 files)
.venv\Scripts\python run_pipeline.py --root "..\OneDrive_2026-11-14\HR Assignment"

# add the local-LLM cross-check (slow on CPU, resumable — stop and restart any time)
.venv\Scripts\python run_pipeline.py --root "..\OneDrive_2026-11-14\HR Assignment" --llm

# Excel in the client's sample layout + Data Quality sheet
.venv\Scripts\python tools\export_excel.py
```

New PDFs: drop them in the folder and re-run. Unchanged files reuse cached results.

## Layout

```
extractor/
  pdfdoc.py        PDF → lines with coordinates; right_of / below / grid_value helpers
  common.py        date / money / identifier normalisers
  parsers/         one module per insurer + detection (add a module to support a new insurer)
  coverage.py      policy type, fire cover, chassis-damage cover + causes (IMT Section I perils)
  normalize.py     canonical OEM / financier / city / state (raw values kept)
  validate.py      all validation rules and severities
  llm_stage.py     Ollama extraction, grounding check, per-file cache
  reconcile.py     rules-vs-LLM verdicts and record status
  db.py            SQLite schema (policies, field_checks, issues, duplicates, vehicles view)
run_pipeline.py    entry point
tools/             census, rules report, Excel export
data/              insurance.db, cached text/JSON, exports  (contains personal data — keep private)
```

## Findings in the current data set (400 PDFs)

- 398 unique policies (2 byte-identical duplicate files), 4 insurers, 0 scanned pages.
- 1 IFFCO policy prints engine and chassis numbers in each other's fields (flagged).
- 16 new vehicles have no registration number on the policy yet (flagged as pending).
- 1 policy in the "expire due Nov–Dec 26" folder was already renewed to Jun 2027.
- Go Digit policies exclude fire/self-ignition **while charging** → Fire Covered = "Yes - Conditional".

## Dashboard

```
run_dashboard.bat            # or: .venv\Scripts\python.exe dashboard\server.py [--asof 2026-12-01]
```

Opens http://127.0.0.1:8050 (bound to localhost only; no internet access needed, no external libraries).

| Screen | What it shows |
|---|---|
| Overview | KPI tiles, expiry timeline, status and insurer split, next expiries, fire / chassis-damage coverage |
| Expiry alerts | Expired / 0–7 / 8–30 / 31–60 day queues |
| Vehicle register | Searchable, filterable, sortable list of all vehicles; CSV export |
| Analytics | Expiries by month, expiry calendar, 12-week workload, city / brand / insurer breakdowns |
| Add policies | Upload PDFs or a whole folder; each is extracted and classified (new vehicle, newer policy, older policy, already in system, same policy number, needs attention); nothing is saved until you confirm; imported PDFs are kept in `data/uploads/<date>/` and listed under Recent imports |
| Vehicle panel | Policy period, fire and chassis-damage cover with covered causes, vehicle and finance details, original PDF, Verified / Needs review tag |

Notifications are in-app (bell). Status is computed live from whichever cover ends first: own-damage or
third-party (third-party is the legally required cover). An alert stays open until
a newer policy PDF for the vehicle is added on the Add policies page, which makes that policy current and closes
the old policy's alerts.

## Database (PostgreSQL 17 in Docker)

```
cp .env.example .env               # then set a real password (both lines)
docker compose up -d               # PostgreSQL on 127.0.0.1:5433 (POSTGRES_PORT), data in the `pgdata` volume
python run_pipeline.py --root "<pdf folder>"
```

| Table | Contents |
|---|---|
| `policies` | one row per unique PDF; typed columns (DATE, NUMERIC, JSONB, TIMESTAMPTZ) |
| `field_checks`, `issues` | per-field rules-vs-LLM audit trail, validation findings |
| `duplicates` | byte-identical PDFs that were skipped |
| `import_log` | upload history |
| `vehicles` (view) | latest policy per chassis number |

The connection string is `DATABASE_URL` (environment variable or `.env`). The schema is created automatically.
`tools/migrate_sqlite_to_pg.py` performed the one-time move from the earlier SQLite files and verifies every value.
