from __future__ import annotations

from collections.abc import Callable

from sakshya.adapters.bank import parse_atm_journal, parse_bank_statement, parse_kyc_account
from sakshya.adapters.base import AdapterContext, ParseResult, Record
from sakshya.adapters.device import parse_call_log, parse_chat, parse_cloud_location, parse_sms
from sakshya.adapters.field import parse_cctv_log, parse_media, parse_seizure_memo
from sakshya.adapters.messages import parse_complaint, parse_email, parse_statement
from sakshya.adapters.network import parse_net_conn, parse_uniaethel
from sakshya.adapters.telecom import parse_cdr, parse_kyc_subscriber, parse_tower_dump, parse_tower_list

ADAPTERS: dict[str, Callable[[AdapterContext], ParseResult]] = {
    "bank_statement": parse_bank_statement,
    "atm_journal": parse_atm_journal,
    "kyc_account": parse_kyc_account,
    "cdr": parse_cdr,
    "tower_list": parse_tower_list,
    "tower_dump": parse_tower_dump,
    "kyc_subscriber": parse_kyc_subscriber,
    "call_log": parse_call_log,
    "sms": parse_sms,
    "chat": parse_chat,
    "cloud_location": parse_cloud_location,
    "email": parse_email,
    "complaint": parse_complaint,
    "statement": parse_statement,
    "net_conn": parse_net_conn,
    "uniaethel": parse_uniaethel,
    "cctv_log": parse_cctv_log,
    "seizure_memo": parse_seizure_memo,
    "media": parse_media,
}

__all__ = ["ADAPTERS", "AdapterContext", "ParseResult", "Record"]
