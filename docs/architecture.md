# Architecture and model

Sakshya runs one pipeline per case. Each stage reads the output of the previous one and nothing is hidden from the investigator: every score is a sum of named terms, and every term names the record it came from.

```
case.yaml + evidence files
  -> intake (hash, ledger)
  -> adapters (one table of observations)
  -> identifiers (canonical entities)
  -> clock correction (offsets, time zones, drift)
  -> link tests (same event, co-presence, impossibility, same actor, sequence)
  -> people (constrained clustering)
  -> indicators
  -> explain (templates, beam search, decision)
  -> reach (money trace, freeze priority)
  -> predict (phase tracking, time to next phase)
  -> decide (evidence requests, fragility)
  -> bundle (workbench) and report
```

## 1. Intake and custody

Each file listed in `case.yaml` is hashed with SHA-256 before it is parsed. The first time a file is seen an `intake` entry is written to `ledger.jsonl`. If the same path later has a different hash the file is flagged and an `intake_changed` entry is written.

The ledger is a hash chain. Each entry holds a sequence number, a time, a type, a payload and the hash of the previous entry, and its own hash is

```
hash_i = SHA-256(canonical_json(seq_i, time_i, type_i, payload_i, hash_{i-1}))
```

Verification walks the chain and reports the first entry that is out of sequence, does not point to its predecessor or was altered. Analyses (with a digest of all inputs, the engine version and the configuration), investigator actions and report exports are all ledger entries.

CCTV frames are checked against the frame hashes in the recorder export log. A frame whose hash differs is reported as altered after export.

## 2. Observations and identifiers

Every adapter emits rows with the same columns: time as recorded, time zone, place (latitude, longitude, radius), amount and direction, the identifiers involved and their roles (holder, counterparty, caller, called, device, ATM and so on), the raw text and a pointer to the file and line.

Identifiers are reduced to canonical entities:

| Kind | Canonical form |
| --- | --- |
| phone | E.164, `+91` added to ten digit Indian mobiles, leading zero removed |
| imei | 15 digits; a 14 digit IMEI gets its Luhn check digit |
| imsi | 14 or 15 digits |
| account | `IFSC:number`; numbers without IFSC become `UNKNOWN:number`; masked numbers keep the last four digits |
| upi, email | lower case |
| mac | lower case, colon separated |
| ip, domain | standard form; `www.` removed from domains |

Names are compared after transliterating Devanagari to Latin with schwa deletion, so `रोहित कुमार` and `Rohit Kumar` compare equal. Name agreement is only ever one term in a link; it never merges people on its own.

## 3. Clock correction

Reference sources (bank statements, ATM journals, CDRs, tower dumps) are trusted for time. Every other file is aligned to them.

For a file *f*, events that also appear in reference records (the same transaction reference, the same call, the same SMS alert) give candidate offsets *d_k = t_ref,k - t_f,k*. The offset is chosen by voting: the candidate with the most other candidates within 90 s wins. It is refined with the median of the supporting votes, and its uncertainty is

```
sigma = max(1.4826 * MAD, floor)
```

An offset within 150 s of a multiple of 30 minutes is reported as a time zone error. With anchors spread over at least three days a drift rate is fitted with the Theil and Sen estimator. Files from the same phone export (call log and SMS) share one clock domain and are estimated together. The residual uncertainty is carried into every later time term.

## 4. Link tests

A link states a claim, for example that a phone was near an ATM when cash was withdrawn. Its weight is the base ten logarithm of a likelihood ratio,

```
W = log10 LR = log10 P(evidence | claim) / P(evidence | coincidence)
```

built as a sum of named terms.

**Time term.** For a gap *dt* with expected value *mu* and combined variance *sigma^2* (both clocks plus the event spread), compared with a uniform time in a window *T*:

```
w_time = log10( T * N(dt; mu, sigma^2) )
```

**Place term.** For a distance *d* between two located observations with radii *r_a* and *r_b*, a Rayleigh distance under the claim against a uniform point in a disc of radius *R* under coincidence:

```
sigma^2 = (r_a^2 + r_b^2) / 4
w_place = log10( pi R^2 / (2 pi sigma^2) ) - d^2 / (2 sigma^2 ln 10)
```

*R* is the area the competing phones were actually spread over, not a fixed city radius, so a cell that covers a whole block does not give a strong place term.

**Attribute terms** follow Fellegi and Sunter. For an attribute that agrees with probability *m* under the claim and *u* by chance:

```
w = log10(m / u)              if the attribute agrees
w = log10((1 - m) / (1 - u))  if it disagrees
```

*u* is taken from frequencies inside the case where possible, so a common surname or a popular bank branch counts for little.

**Rarity term** for co-presence. If *N* phones were on the same cells in the same window and *k* of the others are already linked to the case, an entity linked to the case agrees with *m = 0.5* and *u = (k + 1) / (N + 1)*. Busy locations therefore weaken presence links automatically.

**Combining.** Terms are summed per source and each source is capped at plus or minus 4, so no single file can carry a link:

```
W = sum over sources s of clip( sum of terms from s, -4, +4 )
```

A link is accepted (status `inferred`) when *W* is at least 2 and at least two independent sources contribute. Strong single-source links stay as candidates with a note. Investigators can confirm or reject any link; rejected links are kept and shown.

**Prior and posterior.** Co-presence links carry prior odds of *1 / (N - 1)*, one person out of the crowd, so

```
posterior = (prior_odds * LR_c) / (1 + prior_odds * LR_c)
```

where *LR_c* is the calibrated likelihood ratio (section 10).

Link types:

| Type | Claim | Main terms |
| --- | --- | --- |
| same_event | Two records describe one event (debit and credit, UPI reference and SMS alert, ATM journal and statement) | time, amount, reference agreement |
| co_presence | A phone, handset or cloud account was near a cash withdrawal | time, place, rarity |
| impossibility | A phone could not have been at the withdrawal | travel speed above 120 km/h between a fix and the event |
| same_actor | Two identifiers belong to one person | KYC name and address, registered phone, SIM in handset, shared handset, cloud account device, seizure memo, shared network infrastructure, travelling together |
| sequence | One transfer triggered the next | Hawkes trigger probability |

**Sequence links.** Credits and debits on an account are modelled as a self-exciting process with background rate *mu* and kernel *alpha beta e^(-beta t)*, with *alpha = 0.8*. *beta* is fitted by maximum likelihood over a grid of decay times on the case's own statements. The weight of a link from a credit to a later debit is

```
w_trigger = log10( lambda(t) / mu )
```

and only the latest credit in a burst is credited. A new contact (first seen within 14 days) followed by a payment gives a contact to payment link.

## 5. People

Entities are grouped with union and find over accepted same-actor links at *W >= 2*. Investigator `forbid_merge` decisions are hard constraints: a union that would put two forbidden entities together is refused and recorded. Persons are numbered by their distance from the complainant in the link graph, and only persons tied to the case are shown.

## 6. Indicators

Behavioural indicators are computed per entity and weighted from `config/indicators.yaml`:

* money: received from the complainant, passed on within 60 minutes, split across payees, cash withdrawn, a new account, commission kept, funds retained, long history with the payee;
* communication: contact before payment, lure language, threat language;
* telecom: SIM change shortly before debits, OTP on the new SIM, many SIMs on one handset;
* location: present at a withdrawal, cleared by travel time;
* network: beaconing, large outbound volume, shared infrastructure.

## 7. Explain

A crime template (`config/templates/*.yaml`) lists roles, phases, the indicators that support or contradict each role, variants (for example a knowing or unwitting first-layer mule), the observability of each phase in each source and the typical time between phases.

Beam search binds candidate persons or accounts to roles. The score of a hypothesis *H* is

```
S(H) = prior(H)
     + sum over roles of indicator weights of the bound units
     + sum of accepted co-presence link weights for the cash-out role
     + sum over missing phases of log10(1 - o)
     + order penalties
```

where *o* is the chance the phase would have been seen given the sources in the case. A missing phase that the evidence would almost certainly have shown costs a lot; one that the case simply has no source for costs nothing.

"No offence" is the reference with score 0. The decision rule is:

* the best template is reported when *S >= 2* and it leads every other template and the reference by at least 1;
* otherwise, if suspicious indicators exist, the result is "unknown pattern" and the indicators are listed;
* otherwise the result is "no offence indicated".

The difference in score between two explanations is a log ten likelihood ratio, so a margin of 5.5 reads as the leading explanation fitting the evidence about 316,000 times better.

## 8. Reach

Transfers are built from statements, with debit and credit legs joined by same-event links. Payments from the complainant to payees first seen within 30 days of the complaint are the origin of the trace.

Each account holds a tainted balance. On every debit the tainted share leaves with the money:

* pro-rata: tainted share of the debit = tainted balance / balance before the debit;
* first in, first out: the oldest money leaves first.

Both rules can be shown at any time *as of*, so the trail can be replayed as it stood at any moment. Cash withdrawals end a path. The freeze list ranks accounts by

```
expected recoverable = tainted held * (1 - P(money moves before a freeze lands))
```

For mule accounts bound in the leading hypothesis while cash-out is the next phase, the move probability is the predicted chance that cash-out happens before a freeze can land (section 9). For other accounts a baseline of 0.2 is used.

## 9. Predict

A hidden Markov model runs over the phases of the leading template. Each evidenced event is an observation that favours its phase, and transitions follow the template order. The current phase is the most likely state. The time to the next phase follows a log-normal distribution with the template's median and spread; the engine reports the chance the next phase happens within 15, 30, 60 and 120 minutes and the chance it happens before a freeze can land.

## 10. Calibration

Reported likelihood ratios for co-presence links are calibrated with a single scale factor fitted by log loss on labelled candidates from training cases:

```
W_c = c * W
```

The scale is applied to the reported likelihood ratio, posterior and verbal strength. Acceptance uses the uncalibrated weight, so calibration never changes which links are accepted. The verbal scale follows the example bands of the ENFSI guideline for evaluative reporting (2015).

## 11. Decide

Each possible evidence request (a statement for an account the money reached, CDRs for a number with no call records, a tower dump or CCTV for a withdrawal, hosting records for a domain, a statement from an account holder) is scored by

```
value per day = (expected information gain + gap bonus + money bonus) / days to obtain
```

The information gain is computed over a tempered posterior of the hypotheses (scores divided by 3) so that the ranking does not collapse when one explanation dominates. The fragility check removes the strongest support items one by one until the leading explanation falls behind, and lists them: these are what a defence would challenge first.

## 12. Determinism

Every stage is deterministic. The bundle digest covers all analysis output and excludes only timings and the ledger listing, so the same inputs give the same digest on any machine.
