# Shared incident verifier development results

The shared incident candidate is runnable offline. It failed the recall gate and remains outside the default runtime. The frozen 3.3 source, model weights, classifier head and thresholds match their recorded checksums.

## Decision path

The candidate extracts observation spans with nearby qualifiers, then ranks the category classifier's three most likely labels for each eligible incident. For every nomination, the same decision layer returns supported, compliant or insufficient. It uses the category's evidence requirement in the working policy catalog and applies structured checks for weight comparisons, expiry, required equipment, lease consent and authorized occupancy where the description supplies the necessary facts. The learned path uses a single three-state head for all 29 categories. Only a supported nomination creates a proposed action. A rule statement, an unconfirmed follow-up or an overlong context yields no action on its own.

## Fit and calibration

- The final head was fitted on 14,972 incident-category pairs. The inputs include the existing audited synthetic examples, 427 fit-only operational incident annotations from 245 descriptions, and 87 newly authored fit contrasts. The operational batch includes 144 descriptions with multiple incidents and 29 with both a supported incident and a separate compliant or insufficient one. Only eight categories have operational annotations in all three states.
- The new contrast file supplies one fit family and a separate validation family for every category, with one example of each evidence state in each family. It is synthetic development data. Wrong-category controls include plausible alternative nominations from the saved classifier on audited single-category examples. The calibration set includes 1,402 of these controls and 87 authored contrast pairs.
- The selected validation cutoff accepted 22 of 713 supported pairs and zero of 2,797 negative pairs. Three of the 29 supported authored validation contrasts passed. The model used the frozen multilingual E5 encoder with a newly fitted logistic head. These are calibration results on the same validation set used for selection.

## End-to-end replay

| Development cohort | Shared candidate precision | Shared candidate recall | Exact multi-violation sets |
|---|---:|---:|---:|
| Synthetic validation, 804 descriptions | 93.33% | 5.15% | 0/60 |
| Historical synthetic regression, 804 descriptions | 98.90% | 11.03% | 0/60 |
| Synthetic challenge, 49 descriptions | 72.73% | 12.31% | 0/30 |

Across these cohorts, all 54 clear and 56 abstention records received zero actions. Seven incorrect categories were proposed on records with at least one labeled violation. On the historical synthetic cohort, the previous pilot reached 98.58% precision and 68.01% recall, and frozen 3.3 reached 95.47% precision and 72.30% recall. The earlier shared fit without plausible wrong-category controls reached 64.73% precision and 32.84% recall on that cohort. Training on harder alternative nominations reduced wrong-category findings and reduced recall further.

The candidate flagged records 1, 4 and 7 from the eight-description chat sample, covering expired canned goods still on sale, the 900 g reading with a 1 kg test weight and the missing required extinguisher. Frozen 3.3 flagged records 2 and 8. The chat sample has no independent gold labels and was inspected during development.

The replay cohorts have all been inspected before. The supplied market cohort was excluded because it contributed to fit. A fresh, independently labeled operational evaluation remains pending. The local tokenizer emitted the same load warning as frozen 3.3 and ran with its saved tokenizer. All 25 baseline and 23 candidate unit tests passed.

## Run locally

From the workspace root, pipe one description per line into the evaluator.

```powershell
'900g ang lumalabas sa scale ng vendor kapag nilagay ang 1kg test weight' |
    & .\.venv\Scripts\python.exe candidates/evidence35/scripts/evaluate_shared_incidents.py `
        --artifact candidates/evidence35/artifacts/shared-incident-v3
```

The evaluator emits per-incident decisions and proposed actions as JSON. Pass `--regressions` with a fresh output path to replay the three development cohorts.

[Final regression results](shared-incident-v3-regressions.json) · [Earlier shared fit](shared-incident-regressions.json) · [Training metadata](../artifacts/shared-incident-v3/metadata.json) · [Contrastive data](../data/incident_contrasts.tsv) · [Previous pilot](operational-evidence-recall-v4/REPORT.md)
