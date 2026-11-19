# Automated Recommended Action roadmap

## 1. Prepare ticket descriptions

- [x] Inspect the database handoff and identify `public.tickets.description` as the model input. The handoff contains three developer-entered descriptions. Marikina City Public Market's current practice does not include writing these notes, so use them as development fixtures.
- [ ] Implement shared training and inference preprocessing. Normalize Unicode and whitespace, redact personal identifiers, skip blank or placeholder notes, and preserve Filipino, English and Taglish wording, negation, quantities and units.
- [ ] Track source provenance and description versions at ingestion. Use the ticket ID, vendor ID, status, issue time and update time to identify, deduplicate and filter evidence. Keep developer, synthetic and operational records separate. Allow only known operational records into live ranking and invalidate old decisions when a description changes.

## 2. Build labeled data automatically

- [x] Define the 29 category labels and working evidence boundaries for synthetic data. For example, fish advertised as 1 kg and measured at 850 g supports `WeightMeasures`.
- [x] Generate and review the 120-description `Vendor Identification` pilot across training, validation and test. V2 uses regenerated examples for this category.
- [x] Generate the V2 synthetic dataset for all 29 categories and 20 category pairs. Include single violations, two-violation notes, clear negatives and abstention cases, with Filipino, English and Taglish versions of each scenario.
- [x] Audit `marikina_synthetic_dataset_v2.zip`. Verify 1,340 scenarios and 4,020 descriptions, with 2,412 in training, 804 in validation and 804 in test. Verify that `train_fit.jsonl` has 2,340 rows and excludes abstention cases.
- [x] Verify the two V2 corrections. The known short-weight examples share one training family, and `Lighting Facilities` positives name a vendor maintenance duty. The manifest keeps each declared evidence family in one split. Some families still differ mainly by fixture or fee type, so interpret results as performance on these synthetic scenarios.
- [x] Update the prototype's 13-code `config/taxonomy.csv` and its consumers to use the 29 category labels. Define evidence requirements, working severity and action text for each category.
- [ ] Build operational evaluation data when independent structured evidence is available. Derive labels automatically where the evidence establishes or rules out the exact code. Keep unknown outcomes out of positive and negative targets, and separate operational evaluation data from synthetic and weakly labeled data.

## 3. Train and validate SetFit with Multilingual E5

- [x] Adapt `scripts/train_setfit.py` to accept the V2 JSONL files and preserve the supplied splits. Keep the training floor of eight distinct positive and eight distinct negative descriptions per code.
- [x] Fit a multilabel SetFit model on `train_fit.jsonl` using `intfloat/multilingual-e5-small` and the E5 `query: ` prefix in training and inference. Save the model and its 29-label mapping in `models/setfit-e5-synthetic-v2`. [SetFit multilabel guide](https://huggingface.co/docs/setfit/v1.1.3/en/how_to/multilabel) · [Multilingual E5 model card](https://huggingface.co/intfloat/multilingual-e5-small)
- [x] Select per-category thresholds on validation data. Freeze the thresholds before evaluating the held-out test split once. The model directory contains `thresholds.json` and `evaluation.json` with precision, recall, false positives, support and abstention, including Filipino, English and Taglish breakdowns.
- [ ] Implement automatic live release gates per code. Group operational records by vendor and duplicate or near-duplicate text, and reserve later independent records for the live release test. Enable a code for live recommendations only when it meets the predefined requirements on sufficient operational evidence.

## 4. Accept or abstain automatically

- [x] Route supported category findings automatically from the description to the recommended action. Abstain internally on ambiguous or insufficient descriptions.
- [x] Extract declared and measured quantities from the description and compare compatible mass units. Handle equal weights, short weights, unreliable measurements and vague requests.
- [x] Use the description as the runtime evidence source and remove the user confirmation and structured verification requirements from ingestion.
- [ ] Assess the description-only workflow on independent operational records. Earlier evaluation results that supplied structured verification fields measure the previous workflow.
- [x] Evaluate the supplied 150-record `market_inspection_eval_multilabel.csv` with version 3.3 rules, model and thresholds frozen. Precision was 69.3%, recall 21.3%, with exact label sets on 4 of 100 multi-label records. Actions appeared on 11 of 20 compliant records and 4 of 15 abstention records. Source and labeling independence remain unverified.
- [x] Diagnose all 192 missed labels and review all 27 false actions. An offline fragment-scoring experiment recovered 82 labels but increased compliant records receiving actions to 19 of 20. See [the diagnostic report](evaluation/market-inspection-multilabel/diagnostic/REPORT.md). The baseline artifacts remain frozen; these inspected records are development/regression data for future changes.
- [ ] First require an observed breach within its incident, with applicable internal policy, category boundaries and local compliance/uncertainty handling. Then add context-preserving incident scoring and address remaining model or weight-parser misses. Preserve description-only input and automatic recommendations. Freeze the candidate before evaluating a new untouched set once.
- [x] Implement and isolate a 3.4 development candidate with shared breach checks, incident scoring, internal policy sources and numeric/weight fixes. Its 42 tests and seven isolated DB/API fixtures pass; it fixes all 27 audited false actions and obtains exact sets on 97 of the 100 inspected multi-label records.
- [x] Reject that candidate after broader historical recall falls from 72.3% to 26.6%. Preserve it under `candidates/description34` and restore the frozen 3.3 default byte-for-byte. Reject the validation-only semantic fallback as well. See [the implementation result](evaluation/candidate34/IMPLEMENTATION_REPORT.md).
- [x] Audit the available local datasets. No suitable untouched, independently labeled set under the finalized 29-category contract was established. Prepare developer-only freeze, regression and one-time final-test checks; no system-user steps or switches were added.
- [ ] Train or replace the evidence verifier using representative supported/compliant/insufficient incidents and pass broader coverage regressions before evaluating a new independently labeled test once. This quality gate remains open; the strong result on the inspected 150 records is development evidence only.
- [x] Train two offline three-state evidence verifiers. Reject both after calibration and regression checks. The neural verifier recovered zero additional findings. See [the verifier results](candidates/evidence35/evaluation/TRAINING_REPORT.md).
- [x] Retrain the frozen-encoder verifier with 427 fit-only operational incident annotations. Historical synthetic recall rose from 26.6% to 55.4% relative to strict 3.4, below the frozen 3.3 result of 72.3%. See [the offline pilot results](candidates/evidence35/evaluation/operational-evidence-pilot/REPORT.md).
- [x] Add incident-local recovery to the offline pilot. Historical synthetic recall rose from 55.4% to 63.5% and precision rose from 98.47% to 98.67%. Clear and abstention descriptions received zero actions across the three regression cohorts. See [the recovery results](candidates/evidence35/evaluation/operational-evidence-recall-v2/REPORT.md).
- [x] Evaluate corroborated nominations and explicit incident evidence offline. Historical recall reached 68.01%, compared with 72.30% for frozen 3.3. Clear and abstention descriptions still received zero actions, while one additional incorrect category reduced precision from 98.67% to 98.58%. See [the corroborated pilot results](candidates/evidence35/evaluation/operational-evidence-recall-v4/REPORT.md).

## 5. Count and rank violations across the market

- [ ] Count accepted findings across the entire market using a rolling 30-day window based on ticket issue times. Exclude voided tickets, duplicate records and decisions based on superseded descriptions. Count each distinct ticket once per accepted violation code and require at least two supporting tickets market-wide.
- [ ] Rank qualifying codes by catalog severity (**High Risk → Moderate Risk → Low Risk**), then by distinct ticket count descending within each tier. Break ties by violation code.

## 6. Publish the action narrative and keep it current

- [ ] Adapt `/internal/nlp/recommendations` to publish one short, market-wide paragraph per qualifying violation code using the versioned catalog action. Render only the ordered paragraphs under **Recommended Action** and leave the area empty when no violation qualifies.

> Compare actual product weights with the weights declared to customers and document any discrepancies.

- [ ] Keep decisions, supporting ticket IDs and model, threshold and catalog versions internal. Make updates safe to retry. Refresh the ranking after edits, voids and model releases, and on a schedule so old evidence expires.
- [ ] Run an end-to-end demo with a fixed evaluation date and fixture tickets. Verify that two short-weight tickets from different sections combine into one market-wide count and produce the paragraph above. Test ambiguous notes, retries, risk and frequency ordering, ties, mixed-language and multi-violation notes, edits, voids and expiry.
- [ ] Enable live publication automatically when operational data is available and the release gates pass.
