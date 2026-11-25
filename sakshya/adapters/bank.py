from __future__ import annotations

from sakshya.adapters.base import AdapterContext, ParseResult, Record, get, read_rows, to_float
from sakshya.core.identifiers import canonical


def _tail(account: str) -> str:
    return account.split(":")[-1][-4:] if account else ""


def parse_bank_statement(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    default_account = ctx.entry.get("account", "")
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        account = get(ctx, row, "account") or default_account
        holder = canonical("account", account)
        amount = to_float(get(ctx, row, "amount"))
        direction = get(ctx, row, "direction").upper()[:2]
        channel = get(ctx, row, "channel").upper()
        atm = get(ctx, row, "atm")
        kind = "atm_withdrawal" if channel == "ATM" or atm else "txn"
        record = Record(row=line_no, kind=kind, t_raw=t, raw=raw, amount=amount, direction=direction)
        record.add_id("holder", "account", account)
        record.add_id("counterparty", "account", get(ctx, row, "counterparty_account"))
        record.add_id("counterparty", "upi", get(ctx, row, "counterparty_upi"))
        if atm:
            record.add_id("atm", "atm", atm)
        ref = get(ctx, row, "ref")
        if ref and kind == "txn":
            record.anchors.append(f"ref:{ref}")
        if holder is not None and amount is not None:
            record.anchors.append(f"amt:{amount:.2f}|a4:{_tail(holder.value)}")
            if kind == "atm_withdrawal" and atm:
                record.anchors.append(f"atm:{atm}|amt:{amount:.2f}")
        record.text = get(ctx, row, "narration")
        record.attrs = {
            "channel": channel,
            "balance": to_float(get(ctx, row, "balance")),
            "counterparty_name": get(ctx, row, "counterparty_name"),
            "ref": ref,
            "txn_id": get(ctx, row, "txn_id"),
        }
        result.records.append(record)
    if default_account:
        result.meta["subject"] = [("account", default_account)]
    return result


def parse_atm_journal(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError as exc:
            result.warnings.append(f"row {line_no}: {exc}")
            continue
        atm = get(ctx, row, "atm")
        lat, lon = to_float(get(ctx, row, "lat")), to_float(get(ctx, row, "lon"))
        if atm and lat is not None and lon is not None:
            result.atms[atm] = {"lat": lat, "lon": lon, "radius_m": 20.0, "label": atm}
        amount = to_float(get(ctx, row, "amount"))
        if get(ctx, row, "status").upper() not in {"", "SUCCESS", "OK"}:
            continue
        record = Record(
            row=line_no,
            kind="atm_withdrawal",
            t_raw=t,
            raw=raw,
            amount=amount,
            direction="DR",
            lat=lat,
            lon=lon,
            radius_m=20.0,
            place=atm,
        )
        record.add_id("atm", "atm", atm)
        record.add_id("holder", "account", get(ctx, row, "account"))
        if amount is not None:
            record.anchors.append(f"atm:{atm}|amt:{amount:.2f}")
        record.anchors.append(f"atmcam:{atm}")
        record.attrs = {"journal_id": get(ctx, row, "journal_id")}
        result.records.append(record)
    return result


def parse_kyc_account(ctx: AdapterContext) -> ParseResult:
    result = ParseResult()
    for line_no, row, raw in read_rows(ctx):
        try:
            t = ctx.parse_time(get(ctx, row, "time"))
        except ValueError:
            t = None
        record = Record(row=line_no, kind="kyc", t_raw=t, raw=raw, sigma_t=86400.0)
        record.add_id("subject", "account", get(ctx, row, "account"))
        record.add_id("subject", "upi", get(ctx, row, "upi"))
        record.add_id("registered_phone", "phone", get(ctx, row, "phone"))
        record.attrs = {
            "name": get(ctx, row, "name"),
            "address": get(ctx, row, "address"),
            "kyc": "account",
            "opened_on": get(ctx, row, "time"),
        }
        result.records.append(record)
    return result
