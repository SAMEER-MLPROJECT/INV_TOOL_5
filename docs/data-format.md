# Case format

A case is a folder (or a `.zip` of one) with a manifest called `case.yaml` and the evidence files it lists.

```
CASE-2611-0201/
  case.yaml
  evidence/
    complaint.txt
    bank/statement_victim.csv
    telecom/cdr_9800000000.csv
    ...
```

## Manifest

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
  - {file: evidence/bank/statement_victim.csv, source: bank_statement, account: "IVBK0123456:50100012345678"}
  - {file: evidence/victim_phone/call_log.csv, source: call_log, owner: "+919800000000"}
  - {file: evidence/victim_phone/chat_9811111111.txt, source: chat, owner: "+919800000000", owner_name: "Asha", other: "+919811111111"}
  - {file: evidence/cctv/ATM-1_dvr_log.csv, source: cctv_log, atm_id: ATM-1}
  - {file: evidence/telecom/cdr.csv, source: cdr, colmap: {columns: {time: "Call Start"}, time_format: "%d/%m/%Y %H:%M"}}
```

| Field | Meaning |
| --- | --- |
| `id` | Case identifier: letters, digits, `-` and `_` only |
| `title` | Shown in the workbench and the report |
| `seed.identifiers` | The complainant's identifiers. Money is traced from the seed accounts and people are numbered by their distance from the seed. |
| `evidence[].file` | Path inside the case folder |
| `evidence[].source` | One of the source types below |
| `evidence[].sha256` | Optional hash recorded when the file was received. A mismatch is flagged as critical. |
| `evidence[].account` | For a bank statement, the account it belongs to |
| `evidence[].owner` | For phone exports, the phone number of the handset they came from |
| `evidence[].owner_name`, `other` | For chats, the name the owner appears under and the other party's number |
| `evidence[].atm_id` | For a CCTV log, the ATM the camera covers |
| `evidence[].clock_domain` | Files with the same clock domain share one clock estimate |
| `evidence[].colmap` | Overrides for the column map of this file |

## Column maps

Every tabular source has a default column map in `sakshya/config/colmaps/<source>.yaml`:

```yaml
source: cdr
label: Call detail records
reference: true
timezone: "+05:30"
time_format: "%Y-%m-%d %H:%M:%S"
sigma_s: 2
columns:
  record_id: record_id
  time: start_time
  msisdn: msisdn
```

* `reference` sources are trusted for time; other sources are aligned to them.
* `timezone` is the zone the file was written in: an offset such as `+05:30` or `-04:00`, or `UTC` or `IST`. Times that carry their own offset keep it.
* `time_format` is a Python `strptime` format. Set it to `null` to read ISO 8601 times. Rows whose time does not match are listed as warnings.
* `sigma_s` is the timing uncertainty of the source in seconds.
* `columns` maps the engine's field names (left) to the file's column headers (right).

A `colmap` entry in `case.yaml` is merged over the default, so a file with different headers or another date format needs no code change.

## Source types

| Source | Format | Engine fields |
| --- | --- | --- |
| `bank_statement` | CSV | txn_id, time, account, direction (CR or DR), amount, balance, channel, counterparty_account, counterparty_upi, counterparty_name, ref (UPI reference), atm, narration |
| `atm_journal` | CSV | journal_id, time, atm, lat, lon, account, amount, status |
| `kyc_account` | CSV | account, upi, name, phone, address, time (account opened) |
| `cdr` | CSV | record_id, time, msisdn, other, call_type, duration, imei, imsi, cell |
| `tower_list` | CSV | cell, lat, lon, radius, address |
| `tower_dump` | CSV | record_id, time, cell, msisdn, imei, imsi |
| `kyc_subscriber` | CSV | msisdn, imsi, name, address, document, time (activation) |
| `call_log` | CSV | time, number, type, duration |
| `sms` | CSV | time, sender, direction, body. Bank alerts are read for masked account numbers, UPI references and amounts. |
| `chat` | WhatsApp text export | `dd/mm/yy, h:mm am - Sender: message` lines; continuation lines are joined |
| `cloud_location` | JSON | `{account, device: {phone}, locations: [{timestamp or timestampMs, latitudeE7 and longitudeE7 or lat and lon, accuracy}]}` |
| `email` | RFC 822 `.eml` | From, To, Date, Subject, Received headers, body; URLs, domains, IPs, phones, UPI IDs and account numbers are extracted |
| `net_conn` | CSV | time, src_ip, src_mac, dst_ip, dst_port, dst_host, bytes_out, bytes_in |
| `uniaethel` | JSON | UniAethel incident export: `incidents[]` with host, label, window, counterparty, scores, reasons |
| `cctv_log` | CSV | time, camera, atm, event, frame_file, frame_sha256 |
| `media` | Image | Hashed and matched to `frame_sha256` in the CCTV log |
| `seizure_memo` | CSV | item, time, premises, lat, lon, item_type, description, imei, msisdn, imsi, mac, hostname, officer |
| `complaint` | Text | `Key: value` header lines (Filed, Category, Complainant, Mobile) followed by the narrative |
| `statement` | Text | Same layout as a complaint, with a `Recorded:` line |

Rows that cannot be parsed are counted and listed as warnings on the evidence page; they never stop an analysis.

## Generating test cases

```bash
python -m sakshya generate upi_investment_fraud --seed 7 --out cases
python -m sakshya generate sextortion --seed 3 --scale 5 --out cases
```

Kinds: `upi_investment_fraud`, `sextortion`, `sim_swap_takeover`, `no_offence`, `unknown`. Each generated case includes `truth.json`, the answer key used by the evaluation. The engine never reads it.
