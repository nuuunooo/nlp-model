# Frozen final candidate

Use this snapshot exclusively for final evaluation. Create a separate development version for any changes to the model, cutoff, rules, order, or configuration.

From the project root, use the existing project Python environment to verify the snapshot.

```powershell
& .\.venv\Scripts\python.exe -B evaluation/frozen-final-v4/evaluate.py --verify
```

To evaluate a fresh, independently labeled batch, supply a JSON object with a `records` array. Each record has a `description`, an `expected_decision` of `accept`, `clear`, or `abstain`, and `expected_codes` with the expected category names, an empty list for clear records, or `null` for abstentions. Inference reads only the description.

```powershell
& .\.venv\Scripts\python.exe -B evaluation/frozen-final-v4/evaluate.py --batch final-batch.json --output final-results.json
```

The evaluator checks the snapshot against its SHA-256 inventory before scoring and records the input and snapshot hashes with the results. The benchmark in [the manifest](manifest.json) is the historical development replay. Independent final evaluation is pending.
