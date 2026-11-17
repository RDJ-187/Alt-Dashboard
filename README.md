# Alt Dashboard: Fleet Vehicle Insurance Tracker

Extracts structured data from motor-insurance policy PDFs (Royal Sundaram, ICICI Lombard, IFFCO-Tokio, Go Digit)
and serves an expiry-tracking dashboard for a fleet admin.

- `insurance-tracker/` contains the extraction engine, database layer and dashboard (see its README)
- `plan.md` is the original design plan

Policy PDFs and all extracted data (`insurance-tracker/data/`) are deliberately **not** in this repository:
they contain customer and vehicle details. Run the pipeline locally against your own PDF folder.

## Quick start (Windows)

```
cd insurance-tracker
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run_pipeline.py --root "<folder with policy PDFs>"
run_dashboard.bat
```
