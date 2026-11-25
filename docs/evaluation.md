# Evaluation

Real case files with verified ground truth are not public, so the engine is measured on generated cases whose answer keys are known. The generator writes the same files an investigator would receive (statements, journals, CDRs, tower dumps, KYC, phone exports, chats, email, cloud history, router logs, CCTV logs, seizure memos and complaints) and adds the realistic problems that make correlation hard:

* phone exports written in the wrong time zone, CCTV recorders with clock drift;
* bystanders on the same cells as the cash-out, hundreds per withdrawal;
* decoy people who share a name with a suspect;
* family members who are regular payees of the complainant;
* a CCTV frame altered after export;
* a person whose phone was far away at the time of the withdrawal;
* knowing and unwitting first-layer mules;
* ordinary disputes with no offence, and offences that fit no template.

The answer key (`truth.json`) is written next to each case. The engine never opens it.

## Protocol

```bash
python -m sakshya.evaluation.run --per-kind 6 --training 8 --scales 1,5,20 --fit
```

* **Training cases** (8) are used only to fit the calibration scale for co-presence links.
* **Held-out cases** (6 for each of the five outcomes, 30 in all) use seeds and structural variants that were not used while building the engine.
* **Scaling** runs one case at 1, 5 and 20 times its normal size.
* **Determinism** analyses one case twice and compares the output digests.

Results are written to `sakshya/data/evaluation/results.json` and shown on the **Evaluation** page of the workbench.

## Results

| Rubric line | Measure | Result | Target |
| --- | --- | --- | --- |
| Evidence processing | Records parsed, worst of 16 source types | 100% | 98% or more |
| Cross-source correlation | Same-event links, precision / recall | 0.999 / 0.993 | 0.95 or more |
| | Presence links, precision | 1.000 | 0.95 or more |
| | Identity resolution, precision / recall / F1 | 1.000 / 0.724 / 0.832 | precision 0.95 or more |
| | Decoys wrongly merged | 0 of 20 | none |
| Timeline and reconstruction | Clock offset error, median / worst | 5.8 s / 9.9 s | under 60 s |
| | Wrong time zones detected | 6 of 6 | all |
| | Event ordering (Kendall tau), before / after correction | 0.975 / 0.998 | 0.95 or more after |
| Traceability | Findings with a resolvable evidence pointer | 100% of 2,268 | 100% |
| | Same input gives identical output | yes | yes |
| | Tampered CCTV frames caught | 4 of 4, no false alarms | all |
| Fraud analysis | Accounts reached by the money, precision / recall | 1.000 / 1.000 | 0.95 or more |
| | Cash withdrawn, relative error | 0.55% | under 5% |
| | First-layer mule identified | 100% | 95% or more |
| | Mule variant (knowing or unwitting) | 100% | reported |
| Performance | Analysis time per case, median / worst | 0.25 s / 0.57 s | reported |
| Beyond the rubric | Offence type, including unknown and no offence | 30 of 30 | reported |
| | Cash-out person identified | 100% | reported |
| | Phase tracked during layering, error in predicted cash-out time | 100%, median 12 min | reported |

### Offence type

| Truth \ found | UPI fraud | Sextortion | SIM swap | Unknown | No offence |
| --- | --- | --- | --- | --- | --- |
| UPI fraud | 6 | | | | |
| Sextortion | | 6 | | | |
| SIM swap | | | 6 | | |
| Unknown | | | | 6 | |
| No offence | | | | | 6 |

### Calibration

Share of candidate links that are true, by weight band, over all held-out cases:

| Band | Links | True |
| --- | --- | --- |
| W below 0 | 6,655 | 0.0% |
| W 0 to 1 | 3,232 | 0.0% |
| W 1 to 2 | 1,305 | 1.4% |
| W 2 to 3 | 396 | 99.5% |
| W 3 to 4 | 445 | 100% |
| W 4 and above | 171 | 100% |

The acceptance threshold of 2 separates true from false links cleanly on this data. The fitted co-presence scale is 0.687 (log loss 0.0104 against 0.0179 unscaled on 6,411 training candidates); it shrinks reported likelihood ratios, which were overconfident before fitting.

### Scaling

| Case size | Records | Identifiers | Seconds |
| --- | --- | --- | --- |
| 1x | 3,063 | 1,271 | 0.55 |
| 5x | 5,644 | 5,118 | 1.00 |
| 20x | 15,137 | 19,515 | 2.66 |

## Reading these numbers

The cases are synthetic, so these figures show that the method does what it was designed to do under controlled conditions. They are not a claim of accuracy on real records, which have formats, gaps and errors the generator does not reproduce. Identity resolution recall is deliberately traded for precision: the engine leaves two identifiers apart unless independent records tie them together, because a wrong merge can implicate the wrong person while a missed merge only costs a further request.

Before relying on reported posteriors in a real case, refit the calibration on labelled real cases and confirm the verbal scale against the ENFSI guideline.
