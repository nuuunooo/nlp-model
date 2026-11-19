# Marikina market inspection recommendations

The default development runtime remains frozen version 3.3. An isolated 3.4 candidate fixes the audited multi-violation examples but fails broader recall regressions, so it was not adopted. See the [implementation report](evaluation/candidate34/IMPLEMENTATION_REPORT.md). Neither version has passed a fresh operational release test. The normal description-only, automatic-action workflow is unchanged.

The worker reads each ticket description, classifies supported findings into the 29 categories in `config/taxonomy.csv`, and automatically proposes the corresponding recommended action. Clear descriptions yield no finding. Insufficient, conflicting or ambiguous descriptions produce an internal abstention.

The catalog supplies working severity tiers, evidence requirements and action text. SetFit uses the saved category thresholds, with text checks to discard unrelated category predictions. The E5 `query: ` prefix is shared by training and inference.

## Final evaluation

All final evaluations must use the [frozen final candidate](evaluation/frozen-final-v4/README.md), v4 with the six accepted targeted add-ons. Its [manifest](evaluation/frozen-final-v4/manifest.json) records the cutoff, check order, verification status, and historical benchmark. Create a separate development version before making any changes to this candidate.

## Development database

Use Python 3.11 or 3.12 and PostgreSQL 18. Restore the handoff into an empty development database, apply the schema and seed the catalog.

```powershell
$marketPython = '.\.venv\Scripts\python.exe'
& $marketPython -m pip install -r requirements-setfit.txt
$env:DATABASE_URL = 'postgresql://USER:PASSWORD@localhost:5432/marikina_market_dev'
pg_restore --exit-on-error --no-owner --no-privileges --dbname=$env:DATABASE_URL 'C:/Users/admin/Downloads/marikina_market_db_handoff'
psql $env:DATABASE_URL -v ON_ERROR_STOP=1 -f sql/00_schema.sql
& $marketPython scripts/seed_reference_data.py
```

For an existing development database, apply the schema, seed reference data and use `--reprocess` once to recompute tickets under the description-only pipeline.

## Run automatic recommendations

```powershell
$env:SETFIT_MODEL_DIR = (Resolve-Path models/setfit-e5-synthetic-v2).Path
& $marketPython -m src.db_runner --reprocess
& $marketPython -m uvicorn src.api:app --host 127.0.0.1 --port 8001
```

Subsequent worker runs process ticket updates. Each batch and its watermark commit together. Findings use the current description hash so edited or voided descriptions cease to support published recommendations.

The dashboard reads `/internal/nlp/recommendations` for automatic action proposals and `/internal/nlp/section-insights` for section summaries. Keep these internal routes behind the existing administrator authentication.

## Understand weight descriptions

The pipeline extracts declared and measured quantities from the description, converts compatible mass units and compares their roles. For example, “Fish sold as 1 kg but measured at 850 g” supports a weights-and-measures action. “1 kg declared, 1000 g measured” yields no short-weight finding. Directly described tampering or missing scale registration can also support an action.

Notes about faulty reference scales, unresolved weighing conditions, uncertain transactions or requests such as “Pakicheck ang timbangan” cause abstention. No measurement tolerance is configured, so the comparison treats any described shortfall as short weight.

Only the description supplies evidence for runtime findings. Gold labels, reference identifiers and verification columns in evaluation CSVs are used to assess performance offline.

## Train

The V2 path preserves the supplied training, validation and test splits, fine-tunes multilingual E5 with SetFit, chooses thresholds on validation and evaluates the held-out test once.

```powershell
& $marketPython scripts/train_setfit.py --dataset "$env:USERPROFILE/Downloads/marikina_synthetic_dataset_v2.zip" --output models/setfit-e5-synthetic-v2-new
```

The trainer accepts an extracted dataset directory as well. The reviewed CSV training path uses raw columns `ticket_id,vendor_id,description` and gold columns `ticket_id,gold_codes,annotation_status`. Use category names separated by pipes, such as `WeightMeasures|Sanitation`. Gold data collection is a development evaluation activity.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The tests cover automatic proposals, thresholds, description-only mass comparisons, ambiguity, duplicate suppression and the path from ticket text to an action.
