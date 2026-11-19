# Implementation result: candidate rejected, baseline retained

The approved plan has not reached a release-qualified pipeline. Candidate 3.4 fixes the 27 audited false actions on the inspected 150-record file and detects 97 of 100 complete multi-violation label sets. However, its recall falls substantially on broader historical regression data. It is isolated under `candidates/description34`; the workspace's default source, config and schema have been restored byte-for-byte to the frozen 3.3 snapshot. No production deployment or fresh final test occurred.

The normal workflow remains unchanged: descriptions produce automatic recommended actions or internal abstention. No additional worker/supervisor confirmation, structured evidence entry, or shadow-mode switch was introduced.

## Implemented in the isolated candidate

- Positive breach verification shared by deterministic, model and LLM findings. A topic mention alone cannot create an accepted finding.
- Incident spans retain relevant adjacent requirements, reference-quantity context and follow-up qualifications. Decimals and street initials are protected. A later qualification can invalidate its incident without removing independent findings.
- Internal policy provenance and explicit category boundaries distinguish construction approval, scale registration, vending authorization, business credentials, occupancy and operating rules.
- Numeric comparisons cover compatible quantities, price rates for the same quantity, stated limits, attendance, loading, ages and water-allocation windows. Direct scale-seal and empty-pan faults are recognized.
- Whole-description and incident predictions are batched through the original classifier and thresholds, and accepted categories are deduplicated.
- Evidence text retains its supporting incident context. The optional local LLM receives the complete sanitized description and cannot bypass the evidence contract.
- Reproducible evaluation caches bind scores to model, head, thresholds, tokenizer/config, input layout and scorer identity. Evaluations reject a source change during execution.

The fixed policy catalog records the supplied 2014 code and the [city-hosted ordinance](https://marikina.gov.ph/ordinance/ORDINANCE%20NO.%2011%20S.%202014.pdf). Source checking clarified several prerequisites and exceptions, including blade-display exceptions and permitted knee-length walking shorts. It did not establish a vendor extinguisher duty for the three expiry-only descriptions. The code also refers to separate activity ordinances, and later amendments have not been exhaustively certified. These are working policy interpretations, not a complete current-law certification.

## Development results

All cohorts below were previously inspected or used in development. None is an untouched release test. Gold labels were preserved.

| Cohort | Metric | Frozen 3.3 | Candidate 3.4 |
|---|---|---:|---:|
| Supplied 150 descriptions | Precision on known labels | 69.3% | 100.0% |
| Supplied 150 descriptions | Recall on supplied positive labels | 21.3% | 98.8% |
| Supplied 150 descriptions | Exact sets among 100 multi-label records | 4 | 97 |
| Supplied 150 descriptions | Compliant records receiving actions / 20 | 11 | 0 |
| Supplied 150 descriptions | Abstention records receiving actions / 15 | 4 | 0 |
| Historical synthetic validation | Precision | 98.3% | 100.0% |
| Historical synthetic validation | Recall | 78.8% | 65.1% |
| Historical synthetic validation | Exact multi-label sets / 60 | 42 | 30 |
| Historical synthetic test, now regression | Precision | 95.5% | 100.0% |
| Historical synthetic test, now regression | Recall | 72.3% | 26.6% |
| Historical synthetic test, now regression | Exact multi-label sets / 60 | 36 | 12 |
| Assistant-authored 49-record challenge | Exact multi-label sets / 30 | 19 | 17 |

On the 150-record development file, candidate 3.4 has 241 true-positive labels, zero extra labels and three missing labels. Every previously correct finding is retained. The three withheld Stall Management labels are on `SYN-MI-047`, `SYN-MI-075` and `SYN-MI-101`, where an expired extinguisher is described without establishing the vendor duty. Other supported categories on those records still produce findings. The missing labels were not relabeled or removed from the denominator.

The historical validation and test regressions each retain zero actions on 24 compliant and 24 abstention descriptions. Nevertheless, the recall losses reject the candidate. The strong development-file result is consistent with rules fitted to familiar descriptions, not evidence of broad operational accuracy. The original 150-record frozen-version result remains valid as its baseline; these records cannot become an untouched test for the new candidate.

The separate 49-record challenge is assistant-authored synthetic data, not independent human operational validation. Its candidate precision is 100.0%, recall 72.3%, and false actions on its eight abstention records fall from one to zero.

## Semantic-verifier experiments

Two validation-only experiments tested a pinned local multilingual entailment model, including factual hypothesis alternatives. They were not integrated into the worker. The public model data were downloaded; no inspection descriptions were uploaded.

The factual-hypothesis experiment's highest-recall tested setting reached 98.45% aggregate precision and 77.82% recall on the historical validation cohort, still below the frozen baseline's 78.80% recall. It accepted 104 additional correct labels and eight additional wrong labels relative to that experiment's strict base, an incremental precision of 92.9%. Increasing the cutoff reduced recall. Lowering it further to force a pass would not establish reliable evidence support. No semantic cutoff was adopted and no original classifier threshold was changed.

The experiment uses `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`, revision `8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c`; the quantized ONNX file was checked against the repository's LFS checksum. Its [model card](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli) describes general multilingual NLI training, not certification on these inspection tasks. Cached scores and experiment reports retain their provenance. Their base report predates the final construction/licensing scope correction; they are architecture experiments rather than final candidate metrics.

## Verification and restoration

- The candidate passes 42 tests, including deliberately overconfident nominations, unreliable LLM suggestions, compliance, actor roles, exceptions, quantities, qualifications and numeric boundaries.
- Seven temporary fixtures passed through the isolated PostgreSQL worker and the recommendations, section-insights and review-queue HTTP routes. Accepted findings required no user queue. Edited and voided descriptions stopped supporting findings immediately.
- The temporary candidate fixtures were removed. The isolated development DB was restored to the 3.3 schema and reprocessed with the original model. Zero candidate fixtures and zero 3.4 pipeline rows remained, and the temporary server was stopped.
- The default runtime matches every file hash in `evaluation/frozen-33/manifest.json`. Original weights, head and thresholds are unchanged. All 150 original decisions and finding sources were reproduced exactly from the frozen model scores, and the default's 25 tests pass.

The candidate's frozen manifest records failed recall and multi-label regression gates. Its final-test tool refuses to consume a new test while those gates fail. The baseline remains a development reference, not a newly approved production release.

## Local test-data audit

The available Downloads files did not establish a suitable untouched, independently labeled 29-category test set. Pilot CSVs contain descriptions only. The human-review file has 238 completed and 12 pending reviews under an older 23-code taxonomy, with one review marked as occurring after proposal comparison. Other workbooks are training sources, examples, templates or category-membership files without complete independent current-catalog labels. The current market and weight CSVs have already been evaluated and inspected.

This does not prove that all underlying source records were used in training. It means their available labels and provenance do not meet the current final-test contract. No automatic crosswalk or generated labels were substituted for independent current-catalog labeling. See `test_data_audit.json` for file-level findings.

The prepared developer protocol calls for at least 300 reserved records, including 120 multi-label, 60 compliant and 60 abstention records, with at least ten positive labels for every category. Targets fixed before seeing any fresh test results are precision at least 95%, recall at least 75%, exact sets on at least 70% of multi-label records, and zero false actions in both negative cohorts. These are evaluation targets, not an accuracy guarantee. Provenance and source/vendor/near-duplicate grouping are required offline.

## Outstanding work

1. Replace or train the evidence verifier on representative supported, compliant and insufficient incidents so it preserves coverage across wording and evidence families. The current category classifier alone does not provide that evidence judgment. The narrow candidate and the tested generic NLI fallback both failed this requirement.
2. Resolve remaining policy prerequisites and source-dependent category boundaries internally. Do not infer a vendor duty or a missing permission from a rule statement alone.
3. Pass broader regression gates before reserving or consuming an untouched test. Any further development must use a new candidate version and preserve the rejected snapshot.
4. Obtain independently labeled records under the finalized 29-category contract, freeze the passing candidate, and run the untouched test once. No additional action is needed in the normal user workflow.

## Reproducible artifacts

- `candidates/description34/`: isolated candidate source, config, SQL, tests and tools.
- `candidates/description34/evaluation/candidate34/frozen_candidate.json`: code/model identities and failed gates.
- `market_development_verified.json`, `validation_verified.json`, `test_regression_verified.json`, `challenge_verified.json`: candidate metrics and per-record findings.
- `semantic_validation_experiment.json`, `semantic_validation_facts_experiment.json`: rejected validation-only alternatives.
- `db_verification.json`, `baseline_restore_verification.json`, `test_data_audit.json`: integration, restoration and local-data checks.

Source-hash keys in candidate reports are relative to the isolated candidate checkout, whose files match those hashes. Reports are also retained in the workspace evaluation directory for comparison. The candidate's `models` junction shares the original unchanged model artifacts.
