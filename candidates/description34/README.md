# Description-only candidate 3.4

This candidate is **rejected by development regressions** and is not the default runtime. Its new evidence checks fix the audited operational-description failures, but they lose too much coverage on other wording. The workspace root retains the frozen 3.3 runtime. Neither version has passed a fresh operational release test.

The normal workflow remains description in, automatic recommended actions out, with internal abstention. No worker or supervisor confirmation, shadow-mode switch, or extra runtime evidence fields were added.

Candidate changes include incident context and follow-up qualification, one positive breach contract for rule/model/LLM findings, internal policy provenance and category boundaries, quantity/price/limit comparisons, and batched incident scoring. Original SetFit weights and category thresholds remain unchanged. The separate semantic-verifier experiments were rejected and are not called by the worker.

From this directory, the existing workspace virtual environment runs the 42 candidate tests:

```powershell
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The `models` junction points to the original workspace model artifacts. It avoids duplicating the trained weights. The candidate uses the same weights; this checkout contains its own source, config, SQL, tests and evaluation tools.

`evaluation/candidate34/frozen_candidate.json` records the frozen identity and failed regression gates. `scripts/evaluate_frozen_release.py` refuses to consume a fresh test while those gates fail. The release protocol is developer evaluation tooling and does not change the system-user workflow.

See the workspace [implementation report](../../evaluation/candidate34/IMPLEMENTATION_REPORT.md) for the comparisons, dataset audit and outstanding work. Preserve this rejected snapshot for comparison; a future fix should use a new candidate version and new report paths.
