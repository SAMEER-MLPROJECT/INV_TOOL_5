from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
import pandas as pd

from sakshya.core.config import calibration_scale
from sakshya.core.identifiers import display
from sakshya.links.terms import finalize
from sakshya.model import Link, Term, make_id
from sakshya.money.flows import Statement, Transfer

DAY = 86400.0
ALPHA = 0.8
BETA_GRID_MIN = [5, 10, 20, 40, 80, 160, 320, 640]
NEW_CONTACT_DAYS = 14


def _background(book: Statement | None, outgoing: list[float], span_floor: float = 30 * DAY) -> float:
    if book is not None:
        span = max(book.end - book.start, span_floor)
    elif outgoing:
        span = max(max(outgoing) - min(outgoing), span_floor)
    else:
        span = span_floor
    return max(len(outgoing), 1) / span


def _log_likelihood(beta: float, series: list[tuple[np.ndarray, np.ndarray, float, float]]) -> float:
    total = 0.0
    for credits, debits, mu, horizon in series:
        for t in debits:
            prior = credits[credits < t]
            excitation = ALPHA * beta * np.exp(-beta * (t - prior)).sum() if len(prior) else 0.0
            total += math.log(mu + excitation)
        total -= mu * horizon
        total -= ALPHA * np.sum(1 - np.exp(-beta * (horizon - credits)))
    return total


def fit_beta(transfers: list[Transfer], books: dict[str, Statement]) -> float:
    series = []
    for account, book in books.items():
        credits = np.array([tr.t for tr in transfers if tr.dst == account and tr.kind in {"transfer", "external_in"}])
        debits = np.array([tr.t for tr in transfers if tr.src == account])
        if len(credits) == 0 or len(debits) == 0:
            continue
        origin = book.start
        horizon = max(book.end - origin, DAY)
        mu = _background(book, list(debits))
        series.append((credits - origin, debits - origin, mu, horizon))
    if not series:
        return 1.0 / (20 * 60)
    best = max(BETA_GRID_MIN, key=lambda m: _log_likelihood(1.0 / (m * 60), series))
    return 1.0 / (best * 60)


def sequence_links(
    transfers: list[Transfer], books: dict[str, Statement], obs: pd.DataFrame, cfg: dict, beta: float
) -> list[Link]:
    links: list[Link] = []
    incoming: dict[str, list[Transfer]] = defaultdict(list)
    outgoing: dict[str, list[Transfer]] = defaultdict(list)
    for tr in transfers:
        if tr.dst and not tr.dst.startswith("cash") and tr.kind in {"transfer", "external_in"}:
            incoming[tr.dst].append(tr)
        if tr.src:
            outgoing[tr.src].append(tr)
    for account, outs in outgoing.items():
        ins = incoming.get(account, [])
        if not ins:
            continue
        mu = _background(books.get(account), [o.t for o in outs])
        for out in outs:
            prior = [c for c in ins if 0 < out.t - c.t <= DAY]
            if not prior:
                continue
            phis = [ALPHA * beta * math.exp(-beta * (out.t - c.t)) for c in prior]
            intensity = sum(phis)
            p = intensity / (mu + intensity)
            if p < 0.5:
                continue
            credit = prior[max(range(len(prior)), key=lambda i: phis[i])]
            basis = [credit.obs_ids[0], out.obs_ids[0]]
            source = obs.loc[out.obs_ids[0], "evidence_id"]
            gap = out.t - credit.t
            burst = f"{len(prior)} credits in the previous day" if len(prior) > 1 else "the credit"
            term = Term(
                "trigger",
                math.log10(intensity / mu),
                source,
                f"Outflow {gap / 60:.0f} min after the latest credit; this account normally sends money "
                f"{mu * DAY:.2f} times a day, so {burst} explain it with probability {p:.2f}",
            )
            target = "cash" if out.kind == "cash" else display(out.dst) if out.dst else "an external party"
            link = Link(
                make_id("SQ", credit.key, out.key),
                "sequence",
                basis[0],
                basis[1],
                "obs",
                "obs",
                claim=(
                    f"Rs {out.amount:,.0f} leaving {display(account)} to {target} followed from "
                    f"{'a burst of ' + str(len(prior)) + ' credits' if len(prior) > 1 else 'the credit'} "
                    f"({gap / 60:.0f} min after the latest)"
                ),
                terms=[term],
                basis=basis,
                sources=[source],
                alternatives=["Routine payment unrelated to the credits"],
                defeaters=["Account history showing the same outflow pattern before the credits"],
                extra={
                    "p": round(p, 3),
                    "gap_s": round(gap),
                    "account": account,
                    "mu_per_day": mu * DAY,
                    "beta_min": round(1 / beta / 60, 1),
                    "cash": out.kind == "cash",
                    "credits": len(prior),
                    "credit_obs": [c.obs_ids[0] for c in prior],
                },
            )
            finalize(
                link,
                cfg["cap_per_source"],
                cfg["accept_w"],
                cfg["min_positive_sources"],
                calibration_scale("sequence"),
                cross_source=False,
            )
            links.append(link)
    return links


def contact_payment_links(
    origins: list[Transfer], obs: pd.DataFrame, roles: dict, seeds: list[str], cfg: dict, background_per_day: float
) -> list[Link]:
    links: list[Link] = []
    if not origins:
        return links
    contacts = obs[obs["kind"].isin(["call", "chat", "sms", "email"]) & obs["t"].notna()]
    seed_set = set(seeds)
    beta = 1.0 / (12 * 3600)
    mu = max(background_per_day, 0.05) / DAY
    first_payment = min(tr.t for tr in origins)
    by_party: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
    first_seen: dict[str, float] = {}
    for obs_id, row in contacts.iterrows():
        r = roles.get(obs_id, {})
        parties = set(r.get("from", [])) | set(r.get("to", []))
        if not parties & seed_set:
            continue
        for other in parties - seed_set:
            first_seen[other] = min(first_seen.get(other, float(row["t"])), float(row["t"]))
            if other.startswith(("phone:", "email:")) and row["t"] < first_payment and first_payment - row["t"] <= 7 * DAY:
                by_party[other].append((float(row["t"]), obs_id, row["evidence_id"]))
    by_party = {party: items for party, items in by_party.items() if first_payment - first_seen[party] <= NEW_CONTACT_DAYS * DAY}
    payment = min(origins, key=lambda tr: tr.t)
    pay_source = obs.loc[payment.obs_ids[0], "evidence_id"]
    for party, items in by_party.items():
        items.sort()
        last_t, last_obs, last_source = items[-1]
        gap = first_payment - last_t
        intensity = sum(ALPHA * beta * math.exp(-beta * (first_payment - t)) for t, _, _ in items)
        p = intensity / (mu + intensity)
        term = Term(
            "trigger",
            math.log10(max(intensity, 1e-12) / mu),
            last_source,
            f"{len(items)} contacts in the week before the first payment, the last {gap / 3600:.1f} h before it; "
            f"probability {p:.2f} that the payment followed from them",
        )
        link = Link(
            make_id("SQ", "contact", party, payment.key),
            "sequence",
            party,
            payment.obs_ids[0],
            "entity",
            "obs",
            claim=(
                f"New contact from {display(party)} preceded and plausibly led to the first payment to {display(payment.dst)}"
            ),
            terms=[term, Term("payment", 0.0, pay_source, "First payment to a new payee")],
            basis=[last_obs, payment.obs_ids[0]],
            sources=[last_source, pay_source],
            alternatives=["Unrelated contact that happened before an independent payment"],
            defeaters=["Evidence the complainant planned the payment before the contact"],
            extra={"p": round(p, 3), "contacts": len(items), "gap_s": round(gap), "first_contact_obs": items[0][1]},
        )
        finalize(link, cfg["cap_per_source"], cfg["accept_w"], cfg["min_positive_sources"], calibration_scale("sequence"))
        links.append(link)
    return links
