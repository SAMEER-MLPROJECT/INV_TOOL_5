# Sakshya

Evidence correlation and crime reconstruction engine for cyber fraud investigations.

Sakshya takes the records an investigator already collects in a cyber fraud case (bank statements, ATM journals, call detail records, tower dumps, subscriber and account KYC, phone exports, chats, email, cloud location history, router logs, CCTV recorder logs, seizure memos and the complaint itself) and answers three questions:

1. **Explain.** What happened, who played which role, and how strongly does the evidence support that account over the alternatives, including "no offence".
2. **Reach.** Where did the complainant's money go, where is it still held, and which accounts should be frozen first.
3. **Predict.** Which phase has the offence reached, how soon does the next one usually follow, and which evidence request is worth the most right now.

Every finding points back to a row in a hashed evidence file, and every analysis, investigator decision and report export is written to a hash-chained custody ledger.

## What it does

| Stage | What happens |
| --- | --- |
| Intake | Each file listed in `case.yaml` is hashed with SHA-256 and logged before it is read. CCTV frames are checked against the hashes in the recorder export log. |
| Normalise | 19 source adapters turn files into one table of observations. Phone numbers, IMEIs, accounts, UPI IDs, emails, MAC and IP addresses are put in canonical form. Names in Devanagari and Latin script are compared on a common transliteration. |
| Clock correction | Device clocks and wrong time zones are estimated from events that also appear in reference records (bank, ATM, telecom) by anchor voting, refined with a median and checked for drift. |
| Link testing | Every cross-source link is a likelihood ratio against coincidence: time, place, attribute agreement and rarity terms, capped per source. A link is accepted at a weight of 2 (LR 100) with at least two independent sources. |
| People | Identifiers are grouped into person hypotheses only where accepted links tie them together. Investigator rejections become hard constraints. Common names alone never merge people. |
| Explain | Crime templates (UPI investment fraud, sextortion, SIM swap takeover) are matched by beam search over role bindings and scored against a "no offence" reference. The engine says "unknown pattern" when suspicious activity exists but no template fits clearly. |
| Reach | Money is traced hop by hop with pro-rata or first-in first-out attribution, at any point in time. Accounts are ranked by expected recoverable amount. |
| Predict | A hidden Markov model over template phases estimates the current phase and the time to cash-out. |
| Decide | Evidence requests are ranked by expected information gain, gaps filled and money reachable, per day of effort. A fragility check lists what the conclusion rests on. |
| Report | An HTML case report with evidence pointers, link arithmetic, a hash annex and a clock correction annex. |

## Run it locally

Python 3.11 or newer is required; 3.13 is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sakshya serve --port 8000
```

Open http://localhost:8000. Five demonstration cases are loaded on first start:

| Case | Offence | What it shows |
| --- | --- | --- |
| CASE-2611-0147 | UPI investment fraud | Time zone and drift correction, ATM co-presence, a person cleared by travel time, a tampered CCTV frame, freeze priority |
| CASE-2611-0152 | Sextortion | Threat language, payment, layering and cash-out within hours |
| CASE-2611-0158 | SIM swap takeover | New SIM on a new handset, OTP interception, unauthorised debits |
| CASE-2611-0163 | No offence | An ordinary delivery dispute that must not be labelled as fraud |
| CASE-2611-0171 | Unknown pattern | Data theft with a ransom demand that fits no template |

All names, numbers, banks, domains and addresses in the demonstration data are invented. Domains use the reserved `.test` suffix and IP addresses come from documentation ranges.

## Deploy on Render

The repository contains a `render.yaml` blueprint.

1. Push this folder to a GitHub or GitLab repository.
2. In the Render dashboard choose **New**, then **Blueprint**, and select the repository.
3. Render reads `render.yaml`, installs `requirements.txt` with the Python version in `.python-version` and starts the service. The health check is `/api/health`.

To create the service by hand instead, choose **New**, then **Web Service**, and use:

| Setting | Value |
| --- | --- |
| Runtime | Python |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn sakshya.api.app:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/api/health` |

Uploaded cases and ledgers are stored under `SAKSHYA_WORKSPACE`. On the free plan the disk is reset on every deploy and restart, so uploaded cases do not persist; the demonstration cases are restored automatically. Attach a Render persistent disk and point `SAKSHYA_WORKSPACE` at it to keep uploads. See [docs/deployment.md](docs/deployment.md).

A `Dockerfile` is included for any container host.

## Add a case

Upload a `.zip` from the **Add case** button. The archive holds a `case.yaml` and the evidence files it lists:

```yaml
id: CASE-2611-0201
title: Short description of the case
seed:
  kind: complaint
  identifiers:
    - {type: phone, value: "+919800000000"}
    - {type: account, value: "IVBK0123456:50100012345678"}
evidence:
  - {file: evidence/complaint.txt, source: complaint}
  - {file: evidence/statement.csv, source: bank_statement, account: "IVBK0123456:50100012345678"}
  - {file: evidence/cdr.csv, source: cdr, colmap: {columns: {time: "Call Start"}, time_format: "%d/%m/%Y %H:%M"}}
```

A `colmap` entry maps differently named columns, time formats or time zones without code changes. The supported source types and their columns are listed in [docs/data-format.md](docs/data-format.md).

## Command line

```bash
python -m sakshya serve --port 8000
python -m sakshya analyse path/to/case
python -m sakshya generate upi_investment_fraud --seed 7 --out cases
python -m sakshya demo
python -m sakshya evaluate --per-kind 6 --training 8 --scales 1,5,20
```

`generate` writes a synthetic case with an answer key in `truth.json`. The engine never reads that file; only the evaluation does.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite covers identifier handling, the link arithmetic, money tracing, ledger tamper detection, the full pipeline on the demonstration cases against their answer keys, and the HTTP API including upload safety.

## Evaluation

Measured on 30 held-out generated cases (six of each outcome) that were not used while building the engine:

| Measure | Result |
| --- | --- |
| Records parsed, every source type | 100% |
| Same-event links, precision / recall | 0.999 / 0.993 |
| Presence links, precision | 1.000 |
| Identity resolution, precision / recall | 1.000 / 0.724 |
| Decoys with matching names wrongly merged | 0 of 20 |
| Clock offset error, worst case | 9.9 s |
| Wrong time zones detected | 6 of 6 |
| Event ordering (Kendall tau) before / after correction | 0.975 / 0.998 |
| Findings with a resolvable evidence pointer | 100% of 2,268 |
| Tampered CCTV frames caught | 4 of 4, no false alarms |
| Money trail, precision / recall | 1.000 / 1.000 |
| Offence type, including unknown and no offence | 30 of 30 |
| Analysis time per case, median | 0.25 s |

These figures describe synthetic data only. Real records are messier and the figures should be read as a check that the method works as designed, not as field accuracy. Details are in [docs/evaluation.md](docs/evaluation.md) and on the **Evaluation** page of the workbench.

## Project layout

```
sakshya/
  adapters/      one parser per source type
  api/           FastAPI application and case workspace
  config/        settings, column maps, crime templates, indicators, verbal scale, calibration
  core/          identifiers, geometry, hashing, time and configuration helpers
  custody/       evidence intake and the hash-chained ledger
  decide/        evidence request ranking and fragility check
  evaluation/    metrics and the evaluation runner
  explain/       template matching and hypothesis scoring
  generator/     synthetic case generator with answer keys
  indicators/    behavioural indicators per identifier
  links/         link tests: same event, co-presence, impossibility, same actor, sequence
  money/         transfer building and taint tracing
  normalise/     ingestion, clock estimation, facts
  people/        person clustering under constraints
  predict/       phase tracking and time to next phase
  reach/         freeze priority and linked cases
  report/        HTML case report
  web/           investigator workbench
tests/
docs/
```

## Documentation

* [docs/architecture.md](docs/architecture.md): the model, with the equations behind every score
* [docs/data-format.md](docs/data-format.md): case manifest, source types and column maps
* [docs/evaluation.md](docs/evaluation.md): how the engine is measured
* [docs/deployment.md](docs/deployment.md): Render, Docker and configuration

## Limits

* Templates cover three offence types. Other offences are reported as an unknown pattern, with the suspicious indicators that were found.
* The verbal scale uses the example bands from the ENFSI guideline for evaluative reporting. Confirm them before formal use.
* Calibration was fitted on synthetic cases. Refit it on labelled real cases before relying on reported posteriors.
* The workbench has no user accounts. Run it inside a protected network or behind an authenticating proxy.

## Third-party components

The workbench bundles Cytoscape.js, cytoscape-fcose with layout-base and cose-base, vis-timeline and Leaflet. Their licences are kept next to each library under `sakshya/web/vendor/`. Map tiles are loaded from OpenStreetMap.
