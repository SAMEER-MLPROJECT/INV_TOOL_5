from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Any

from sakshya.core.timeutil import IST, UTC
from sakshya.generator.world import Atm, Bank, Person, Tower, World
from sakshya.generator.writer import CaseWriter, RowRef, TableFile, frame_hash, json_text, png_bytes

STATEMENT_COLUMNS = [
    "txn_id",
    "value_time",
    "account",
    "direction",
    "amount",
    "balance",
    "channel",
    "counterparty_account",
    "counterparty_upi",
    "counterparty_name",
    "upi_ref",
    "atm_id",
    "narration",
]
CDR_COLUMNS = ["record_id", "start_time", "msisdn", "other_party", "call_type", "duration_s", "imei", "imsi", "cell_id"]
DUMP_COLUMNS = ["record_id", "seen_time", "cell_id", "msisdn", "imei", "imsi"]
JOURNAL_COLUMNS = ["journal_id", "txn_time", "atm_id", "atm_lat", "atm_lon", "account", "amount", "status"]
CCTV_COLUMNS = ["frame_time", "camera_id", "atm_id", "event", "frame_file", "frame_sha256"]
NET_COLUMNS = ["ts", "src_ip", "src_mac", "dst_ip", "dst_port", "dst_host", "bytes_out", "bytes_in"]
SEIZURE_COLUMNS = [
    "item_id",
    "seized_time",
    "premises",
    "premises_lat",
    "premises_lon",
    "item_type",
    "description",
    "imei",
    "msisdn",
    "imsi",
    "mac",
    "hostname",
    "officer",
]


@dataclass
class Pending:
    ref: RowRef | None = None


@dataclass
class StatementBook:
    holder: Person
    bank: Bank
    account: str
    opening: float
    events: list[tuple[datetime, dict[str, Any], Pending]] = field(default_factory=list)


def ist(moment: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return moment.astimezone(IST).strftime(fmt)


class Builder:
    def __init__(self, world: World, writer: CaseWriter) -> None:
        self.w = world
        self.cw = writer
        self.books: dict[str, StatementBook] = {}
        self.cdrs: dict[str, TableFile] = {}
        self.account_info: dict[str, dict[str, Any]] = {}
        self.victim_phone: str | None = None
        self.victim_export_utc = False
        self.call_log: TableFile | None = None
        self.sms_log: TableFile | None = None
        self.chat_lines: dict[str, list[tuple[datetime, str, str | None]]] = {}
        self.chat_meta: dict[str, dict[str, str]] = {}
        self.journals: dict[str, TableFile] = {}
        self.cctv: dict[str, dict[str, Any]] = {}
        self.dumps: dict[str, TableFile] = {}
        self.towers_used: set[str] = set()
        self.truth: dict[str, Any] = {
            "same_event": [],
            "co_presence": [],
            "impossible": [],
            "events": [],
            "persons": {},
            "roles": {},
            "variants": {},
            "clock": {},
            "tampered": [],
            "decoy_pairs": [],
            "money": {},
        }
        self.pending_truth: list[tuple[str, Any]] = []
        self.counter = 0

    def next_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter:06d}"

    def register_account(self, account: str, holder: Person, bank: Bank) -> None:
        self.account_info[account] = {"holder": holder, "bank": bank, "upi": holder.upis.get(account, "")}

    def open_statement(self, account: str, opening: float) -> None:
        info = self.account_info[account]
        self.books[account] = StatementBook(info["holder"], info["bank"], account, opening)

    def _statement_event(self, account: str, moment: datetime, row: dict[str, Any]) -> Pending:
        pending = Pending()
        if account in self.books:
            self.books[account].events.append((moment, row, pending))
        return pending

    def transfer(
        self, src: str, dst: str, amount: float, moment: datetime, channel: str = "UPI", note: str = ""
    ) -> tuple[Pending, Pending, str]:
        ref = self.w.upi_ref()
        src_info, dst_info = self.account_info[src], self.account_info[dst]
        debit = self._statement_event(
            src,
            moment,
            {
                "direction": "DR",
                "amount": amount,
                "channel": channel,
                "counterparty_account": dst,
                "counterparty_upi": dst_info["upi"],
                "counterparty_name": dst_info["holder"].name,
                "upi_ref": ref,
                "narration": f"{channel}/{ref}/{note or 'Payment'}",
            },
        )
        credit_moment = moment + timedelta(seconds=self.w.rng.randint(1, 6))
        credit = self._statement_event(
            dst,
            credit_moment,
            {
                "direction": "CR",
                "amount": amount,
                "channel": channel,
                "counterparty_account": src,
                "counterparty_upi": src_info["upi"],
                "counterparty_name": src_info["holder"].name,
                "upi_ref": ref,
                "narration": f"{channel}/{ref}/{note or 'Payment'}",
            },
        )
        if src in self.books and dst in self.books:
            self.pending_truth.append(("same_event", (debit, credit)))
        return debit, credit, ref

    def external_credit(self, dst: str, amount: float, moment: datetime, name: str, note: str, channel: str = "NEFT") -> Pending:
        return self._statement_event(
            dst,
            moment,
            {
                "direction": "CR",
                "amount": amount,
                "channel": channel,
                "counterparty_account": "",
                "counterparty_upi": "",
                "counterparty_name": name,
                "upi_ref": self.w.upi_ref(),
                "narration": f"{channel}/{note}",
            },
        )

    def external_debit(
        self, src: str, amount: float, moment: datetime, name: str, note: str, channel: str = "POS", upi: str = ""
    ) -> Pending:
        return self._statement_event(
            src,
            moment,
            {
                "direction": "DR",
                "amount": amount,
                "channel": channel,
                "counterparty_account": "",
                "counterparty_upi": upi,
                "counterparty_name": name,
                "upi_ref": self.w.upi_ref(),
                "narration": f"{channel}/{note}",
            },
        )

    def journal(self, atm: Atm) -> TableFile:
        if atm.atm_id not in self.journals:
            self.journals[atm.atm_id] = self.cw.table(
                f"bank/atm_journal_{atm.atm_id}.csv", "atm_journal", JOURNAL_COLUMNS, sort_key="__sort"
            )
        return self.journals[atm.atm_id]

    def enable_cctv(self, atm: Atm, offset_s: float, tamper_index: int | None = None) -> None:
        self.cctv[atm.atm_id] = {
            "atm": atm,
            "offset": offset_s,
            "rows": [],
            "frames": 0,
            "tamper": tamper_index,
            "table": self.cw.table(
                f"cctv/{atm.atm_id}_dvr_log.csv", "cctv_log", CCTV_COLUMNS, sort_key="__sort", atm_id=atm.atm_id
            ),
        }

    def withdraw(
        self, account: str | None, atm: Atm, amount: float, moment: datetime, masked: str | None = None, frame: bool = False
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if account is not None:
            result["statement"] = self._statement_event(
                account,
                moment,
                {
                    "direction": "DR",
                    "amount": amount,
                    "channel": "ATM",
                    "counterparty_account": "",
                    "counterparty_upi": "",
                    "counterparty_name": "Cash withdrawal",
                    "upi_ref": self.w.upi_ref(),
                    "atm_id": atm.atm_id,
                    "narration": f"ATM/{atm.atm_id}/CASH",
                },
            )
        journal = self.journal(atm)
        shown = (
            account
            if account and self.account_info.get(account, {}).get("bank") and self.account_info[account]["bank"].code == atm.bank
            else None
        )
        if shown is None:
            tail = (account.split(":")[-1][-4:]) if account else (masked or str(self.w.rng.randint(1000, 9999)))
            shown = "XXXXXXXX" + tail
        result["journal"] = journal.add(
            {
                "__sort": moment.isoformat(),
                "journal_id": self.next_id("J"),
                "txn_time": ist(moment),
                "atm_id": atm.atm_id,
                "atm_lat": atm.lat,
                "atm_lon": atm.lon,
                "account": shown,
                "amount": f"{amount:.2f}",
                "status": "SUCCESS",
            }
        )
        if "statement" in result:
            self.pending_truth.append(("same_event", (result["statement"], result["journal"])))
        cam = self.cctv.get(atm.atm_id)
        if cam is not None:
            shift = cam["offset"] + self.w.rng.uniform(-8, 8)
            frame_time = moment + timedelta(seconds=shift + self.w.rng.uniform(-20, 20))
            frame_file = ""
            frame_sha = ""
            if frame:
                cam["frames"] += 1
                index = cam["frames"]
                content = png_bytes(48, 32, self.w.seed * 100 + index)
                frame_sha = frame_hash(content)
                frame_file = f"cctv/frames/{atm.atm_id}_{index:03d}.png"
                if cam["tamper"] == index:
                    content = png_bytes(48, 32, self.w.seed * 100 + index, shade=120)
                    self.truth["tampered"].append(f"evidence/{frame_file}")
                self.cw.blob(frame_file, "media", content)
            result["cctv"] = cam["table"].add(
                {
                    "__sort": frame_time.isoformat(),
                    "frame_time": ist(frame_time, "%d/%m/%Y %H:%M:%S"),
                    "camera_id": "CAM-01",
                    "atm_id": atm.atm_id,
                    "event": "CUSTOMER_AT_ATM",
                    "frame_file": frame_file,
                    "frame_sha256": frame_sha,
                }
            )
            self.truth["same_event"].append([result["journal"], result["cctv"]])
        return result

    def cdr(self, msisdn: str) -> TableFile:
        if msisdn not in self.cdrs:
            self.cdrs[msisdn] = self.cw.table(f"telecom/cdr_{msisdn[1:]}.csv", "cdr", CDR_COLUMNS, sort_key="__sort")
        return self.cdrs[msisdn]

    def cdr_row(
        self, msisdn: str, moment: datetime, other: str, call_type: str, duration: int, imei: str, imsi: str, tower: Tower
    ) -> RowRef | None:
        if msisdn not in self.cdrs:
            return None
        self.towers_used.add(tower.cell_id)
        return self.cdrs[msisdn].add(
            {
                "__sort": moment.isoformat(),
                "record_id": self.next_id("C"),
                "start_time": ist(moment),
                "msisdn": msisdn,
                "other_party": other,
                "call_type": call_type,
                "duration_s": duration,
                "imei": imei,
                "imsi": imsi,
                "cell_id": tower.cell_id,
            }
        )

    def victim_device(self, phone: str, utc_export: bool) -> None:
        self.victim_phone = phone
        self.victim_export_utc = utc_export
        self.call_log = self.cw.table(
            "victim_phone/call_log.csv", "call_log", ["timestamp", "number", "type", "duration"], sort_key="__sort", owner=phone
        )
        self.sms_log = self.cw.table(
            "victim_phone/sms.csv", "sms", ["timestamp", "sender", "direction", "body"], sort_key="__sort", owner=phone
        )

    def _export_time(self, moment: datetime) -> str:
        if self.victim_export_utc:
            return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
        return ist(moment)

    def call(
        self,
        caller: tuple[str, str, str, Tower],
        callee: tuple[str, str, str, Tower],
        moment: datetime,
        duration: int,
        kind: str = "VOICE",
    ) -> None:
        a, a_imei, a_imsi, a_tower = caller
        b, b_imei, b_imsi, b_tower = callee
        refs = []
        mo = self.cdr_row(a, moment, b, f"{kind}-MO", duration, a_imei, a_imsi, a_tower)
        mt = self.cdr_row(b, moment + timedelta(seconds=1), a, f"{kind}-MT", duration, b_imei, b_imsi, b_tower)
        refs.extend([r for r in (mo, mt) if r])
        if self.call_log is not None and self.victim_phone in (a, b) and kind == "VOICE":
            other = b if a == self.victim_phone else a
            direction = "outgoing" if a == self.victim_phone else "incoming"
            log_moment = moment + timedelta(seconds=self.w.rng.randint(-2, 2))
            ref = self.call_log.add(
                {
                    "__sort": log_moment.isoformat(),
                    "timestamp": self._export_time(log_moment),
                    "number": other,
                    "type": direction,
                    "duration": duration,
                }
            )
            refs.append(ref)
        if len(refs) >= 2:
            for i in range(len(refs) - 1):
                self.truth["same_event"].append([refs[i], refs[i + 1]])

    def sms_to_victim(self, moment: datetime, sender: str, body: str) -> RowRef | None:
        if self.sms_log is None:
            return None
        return self.sms_log.add(
            {
                "__sort": moment.isoformat(),
                "timestamp": self._export_time(moment),
                "sender": sender,
                "direction": "inbox",
                "body": body,
            }
        )

    def chat(self, other: str, owner_name: str, other_label: str) -> None:
        self.chat_lines.setdefault(other, [])
        self.chat_meta[other] = {"owner_name": owner_name, "other_label": other_label}

    def say(self, other: str, moment: datetime, from_owner: bool, text: str, tag: str | None = None) -> None:
        self.chat_lines[other].append((moment, "owner" if from_owner else "other", text if tag is None else f"{tag}\x00{text}"))

    def dump(self, atm: Atm) -> TableFile:
        if atm.atm_id not in self.dumps:
            self.dumps[atm.atm_id] = self.cw.table(
                f"telecom/tower_dump_{atm.atm_id}.csv", "tower_dump", DUMP_COLUMNS, sort_key="__sort"
            )
        return self.dumps[atm.atm_id]

    def dump_row(self, atm: Atm, moment: datetime, tower: Tower, msisdn: str, imei: str, imsi: str) -> RowRef:
        self.towers_used.add(tower.cell_id)
        return self.dump(atm).add(
            {
                "__sort": moment.isoformat(),
                "record_id": self.next_id("D"),
                "seen_time": ist(moment),
                "cell_id": tower.cell_id,
                "msisdn": msisdn,
                "imei": imei,
                "imsi": imsi,
            }
        )

    def background_dump(self, atm: Atm, start: datetime, end: datetime, count: int) -> None:
        covering = self.w.towers_covering(atm.lat, atm.lon, 1200) or [self.w.tower_near(atm.lat, atm.lon)]
        span = (end - start).total_seconds()
        for _ in range(count):
            msisdn, imei, imsi = self.w.phone(), self.w.imei(), self.w.imsi()
            for _ in range(self.w.rng.randint(1, 3)):
                moment = start + timedelta(seconds=self.w.rng.uniform(0, span))
                self.dump_row(atm, moment, self.w.rng.choice(covering), msisdn, imei, imsi)

    def finalize(self) -> None:
        for account, book in self.books.items():
            table = self.cw.table(
                f"bank/statement_{account.split(':')[1][-6:]}.csv",
                "bank_statement",
                STATEMENT_COLUMNS,
                sort_key="__sort",
                account=account,
            )
            balance = book.opening
            for moment, row, pending in sorted(book.events, key=lambda item: item[0]):
                balance += row["amount"] if row["direction"] == "CR" else -row["amount"]
                pending.ref = table.add(
                    {
                        "__sort": moment.isoformat(),
                        "txn_id": self.next_id("T"),
                        "value_time": ist(moment, "%d-%m-%Y %H:%M:%S"),
                        "account": account,
                        "direction": row["direction"],
                        "amount": f"{row['amount']:.2f}",
                        "balance": f"{balance:.2f}",
                        "channel": row["channel"],
                        "counterparty_account": row.get("counterparty_account", ""),
                        "counterparty_upi": row.get("counterparty_upi", ""),
                        "counterparty_name": row.get("counterparty_name", ""),
                        "upi_ref": row.get("upi_ref", ""),
                        "atm_id": row.get("atm_id", ""),
                        "narration": row.get("narration", ""),
                    }
                )
        for other, lines in self.chat_lines.items():
            meta = self.chat_meta[other]
            text = self.cw.text(
                f"victim_phone/whatsapp_chat_{other[-10:]}.txt",
                "chat",
                owner=self.victim_phone,
                owner_name=meta["owner_name"],
                other=other,
            )
            text.add(
                "Messages and calls are end-to-end encrypted. "
                "No one outside of this chat, not even WhatsApp, can read or listen to them."
            )
            for moment, who, body in sorted(lines, key=lambda item: item[0]):
                tag = None
                if "\x00" in body:
                    tag, body = body.split("\x00", 1)
                stamp = moment.astimezone(IST).strftime("%d/%m/%y, %I:%M %p").replace("AM", "am").replace("PM", "pm")
                speaker = meta["owner_name"] if who == "owner" else meta["other_label"]
                ref = text.add(f"{stamp} - {speaker}: {body}")
                if tag:
                    self.cw.tag(tag, ref)
        for kind, payload in self.pending_truth:
            if kind == "same_event":
                left, right = payload
                left_ref = left.ref if isinstance(left, Pending) else left
                right_ref = right.ref if isinstance(right, Pending) else right
                if left_ref is not None and right_ref is not None:
                    self.truth["same_event"].append([left_ref, right_ref])
        if self.towers_used:
            table = self.cw.table(
                "telecom/tower_list.csv", "tower_list", ["cell_id", "lat", "lon", "radius_m", "address"], sort_key="cell_id"
            )
            for tower in self.w.towers:
                if tower.cell_id in self.towers_used:
                    table.add(
                        {
                            "cell_id": tower.cell_id,
                            "lat": tower.lat,
                            "lon": tower.lon,
                            "radius_m": tower.radius_m,
                            "address": tower.address,
                        }
                    )
        self.truth = self._resolve(self.truth)

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, Pending):
            return value.ref
        if isinstance(value, dict):
            return {k: self._resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v) for v in value]
        if isinstance(value, tuple):
            return [self._resolve(v) for v in value]
        return value

    def email(
        self,
        name: str,
        sender: tuple[str, str],
        recipient: tuple[str, str],
        moment: datetime,
        subject: str,
        body: str,
        origin_ip: str,
        extra_headers: dict[str, str] | None = None,
    ) -> RowRef:
        relay = sender[1].split("@")[1]
        stamp = format_datetime(moment.astimezone(IST))
        headers = [
            f"Received: from mail-relay.{relay} ([{origin_ip}]) by mx.mail.test; {stamp}",
            f"From: {sender[0]} <{sender[1]}>",
            f"To: {recipient[0]} <{recipient[1]}>",
            f"Subject: {subject}",
            f"Date: {format_datetime(moment.astimezone(IST))}",
            f"Message-ID: <{self.w.rng.randint(10**8, 10**9)}.{self.w.seed}@{sender[1].split('@')[1]}>",
            f"X-Originating-IP: [{origin_ip}]",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=utf-8",
        ]
        for key, value in (extra_headers or {}).items():
            headers.append(f"{key}: {value}")
        text = self.cw.text(f"email/{name}", "email")
        text.add("\n".join(headers) + "\n\n" + body)
        return RowRef(f"email/{name}", 0)

    def kyc_tables(
        self, subscribers: list[tuple[str, str, str, str, str]], accounts: list[tuple[str, str, str, str, str, str]]
    ) -> None:
        if subscribers:
            table = self.cw.table(
                "telecom/kyc_subscribers.csv",
                "kyc_subscriber",
                ["msisdn", "imsi", "subscriber_name", "address", "id_document", "activation_date"],
                sort_key="msisdn",
            )
            for msisdn, imsi, name, address, activated in subscribers:
                table.add(
                    {
                        "msisdn": msisdn,
                        "imsi": imsi,
                        "subscriber_name": name,
                        "address": address,
                        "id_document": f"Aadhaar XXXX XXXX {self.w.rng.randint(1000, 9999)}",
                        "activation_date": activated,
                    }
                )
        if accounts:
            table = self.cw.table(
                "bank/kyc_accounts.csv",
                "kyc_account",
                ["account", "upi", "holder_name", "registered_phone", "address", "opened_on"],
                sort_key="account",
            )
            for account, upi, name, phone, address, opened in accounts:
                table.add(
                    {
                        "account": account,
                        "upi": upi,
                        "holder_name": name,
                        "registered_phone": phone,
                        "address": address,
                        "opened_on": opened,
                    }
                )

    def cloud(self, account: str, device_phone: str, points: list[tuple[datetime, float, float, int]]) -> dict[datetime, int]:
        records = []
        rows: dict[datetime, int] = {}
        for index, (moment, lat, lon, accuracy) in enumerate(sorted(points)):
            records.append(
                {
                    "timestamp": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "latitudeE7": int(round(lat * 1e7)),
                    "longitudeE7": int(round(lon * 1e7)),
                    "accuracy": accuracy,
                }
            )
            rows[moment] = index + 1
        payload = {"account": account, "device": {"phone": device_phone, "model": "Android handset"}, "locations": records}
        text = self.cw.text("cloud/location_history.json", "cloud_location", raw_json=True)
        text.add(json_text(payload))
        return rows

    def net_table(self) -> TableFile:
        return self.cw.table("network/router_conn_log.csv", "net_conn", NET_COLUMNS, sort_key="__sort")

    def net(self, moment: datetime, src_ip: str, mac: str, dst_ip: str, port: int, host: str, out_b: int, in_b: int) -> RowRef:
        ts = moment.timestamp()
        return self.net_table().add(
            {
                "__sort": f"{ts:016.3f}",
                "ts": f"{ts:.3f}",
                "src_ip": src_ip,
                "src_mac": mac,
                "dst_ip": dst_ip,
                "dst_port": port,
                "dst_host": host,
                "bytes_out": out_b,
                "bytes_in": in_b,
            }
        )

    def seizure(self, rows: list[dict[str, Any]]) -> None:
        table = self.cw.table("seizure/seizure_memo.csv", "seizure_memo", SEIZURE_COLUMNS, sort_key="item_id")
        for row in rows:
            table.add(row)
