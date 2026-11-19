# Recall gap follow-up

The target was 35 more correct historical findings at precision of at least 98.58%, with zero actions on clear and abstention descriptions. None of the three recovery experiments met the historical recall target. The best broad pilot remains the corroborated offline pilot at 555 of 816 correct findings, 68.01% recall, and 98.58% precision. Frozen 3.3 gets 590 correct findings in the same historical cohort.

## Experiments

| Offline experiment | Validation result | Historical result |
| --- | --- | --- |
| Nearest fit evidence, comparing same-category supported and unsupported examples | No rule added findings from at least two scenarios without adding an incorrect finding | No rule qualified for replay |
| Explicit observed breaches, including construction approval, stall use, disruption, traffic, and scale alteration | Added 21 correct findings and zero incorrect ones. Recall rose from 78.92% to 81.50% and precision from 99.69% to 99.70%. | Added zero findings. Recall stayed at 68.01%, precision at 98.58%, and exact multi-violation sets at 34/60. |
| Separately fitted per-category lexical evidence heads with incident-level corroboration | No rule added findings from at least two scenarios without adding an incorrect finding | No rule qualified for replay |

The explicit checks were selected on validation and fixed before replay. Across validation and the two historical cohorts, the checks produced zero actions on 54 clear and 56 abstention descriptions. The lexical and nearest-evidence models used existing fit examples, including the audited 427 operational incident labels, and did not use any historical labels for selection. The explicit validation gain did not transfer to the broader synthetic cohort.

## Historical miss inventory

The best pilot misses 261 expected findings. Of these, 115 have no eligible incident under its learned recovery checks, 85 have an eligible incident below the frozen category threshold, and 61 have an eligible incident that reaches that threshold but are still rejected by recovery. This inventory describes the existing pipeline stages. A rejected case may lack sufficient evidence in the description.

Frozen 3.3 gets 63 correct findings that the pilot misses. The pilot gets 28 correct findings that frozen 3.3 misses. The net gap is 35 findings. The most frequent categories among the 146 eligible misses are Liquor and Bladed Instruments at 19 each, Price Monitoring at 14, and Traffic and Porter Regulation at 12 each.

The 25 baseline tests and 15 candidate tests passed. Frozen 3.3 source and model hashes match. The experiments are offline and use previously inspected regression cohorts. An independent operational test is pending.
