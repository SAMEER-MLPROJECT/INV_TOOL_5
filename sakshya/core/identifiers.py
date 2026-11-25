from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from indic_transliteration import sanscript
from indic_transliteration.sanscript import transliterate
from rapidfuzz import fuzz

PERSON_TYPES = frozenset({"phone", "imei", "imsi", "account", "upi", "email", "mac", "host", "cloud"})
DISPLAY_NAMES = {
    "phone": "Phone",
    "imei": "Handset (IMEI)",
    "imsi": "SIM (IMSI)",
    "account": "Bank account",
    "account_masked": "Masked account",
    "upi": "UPI ID",
    "email": "Email",
    "ip": "IP address",
    "mac": "Device (MAC)",
    "host": "Device (hostname)",
    "cloud": "Cloud account",
    "atm": "ATM",
    "cell": "Cell site",
    "domain": "Domain",
    "sender": "SMS sender",
}

_DIGITS = re.compile(r"\D+")
_IFSC_PAIR = re.compile(r"([A-Z]{4}0[A-Z0-9]{6})[^A-Z0-9]+(\d{6,20})")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HONORIFICS = {"mr", "mrs", "ms", "miss", "shri", "sri", "smt", "kumari", "km", "dr", "md", "mohd"}
_CONSONANT = set("bcdfghjklmnpqrstvwxyzBCDFGHJKLMNPQRSTVWXYZ")


@dataclass(frozen=True, slots=True)
class Identifier:
    kind: str
    value: str

    @property
    def entity(self) -> str:
        return f"{self.kind}:{self.value}"


def canonical_phone(raw: str) -> str | None:
    text = str(raw).strip()
    if not text:
        return None
    digits = _DIGITS.sub("", text)
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    if len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        return "+91" + digits[1:]
    if text.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    return None


def luhn_valid(number: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def canonical_imei(raw: str) -> str | None:
    digits = _DIGITS.sub("", str(raw))
    if len(digits) == 14:
        for check in range(10):
            if luhn_valid(digits + str(check)):
                return digits + str(check)
    if len(digits) == 15:
        return digits
    return None


def canonical_imsi(raw: str) -> str | None:
    digits = _DIGITS.sub("", str(raw))
    return digits if 14 <= len(digits) <= 15 else None


def canonical_account(raw: str) -> tuple[str, str] | None:
    text = str(raw).strip().upper().replace(" ", "")
    if not text:
        return None
    if ":" in text:
        ifsc, number = text.split(":", 1)
        number = _DIGITS.sub("", number)
        if number:
            return "account", f"{ifsc}:{number}"
        return None
    paired = _IFSC_PAIR.fullmatch(text)
    if paired:
        return "account", f"{paired.group(1)}:{paired.group(2)}"
    masked = re.fullmatch(r"[X*]+(\d{3,6})", text)
    if masked:
        return "account_masked", masked.group(1)[-4:]
    digits = _DIGITS.sub("", text)
    if len(digits) >= 9:
        return "account", f"UNKNOWN:{digits}"
    return None


def canonical_upi(raw: str) -> str | None:
    text = str(raw).strip().lower()
    return text if re.fullmatch(r"[a-z0-9._\-]{2,64}@[a-z][a-z0-9.\-]{1,32}", text) else None


def canonical_email(raw: str) -> str | None:
    text = str(raw).strip().strip("<>").lower()
    return text if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", text) else None


def canonical_ip(raw: str) -> str | None:
    try:
        return str(ipaddress.ip_address(str(raw).strip()))
    except ValueError:
        return None


def canonical_mac(raw: str) -> str | None:
    digits = re.sub(r"[^0-9a-fA-F]", "", str(raw))
    if len(digits) != 12:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).lower()


def domain_of(url: str) -> str | None:
    text = str(url).strip()
    if "://" not in text:
        text = "https://" + text
    host = urlparse(text).hostname
    if not host:
        return None
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


_CANON = {
    "phone": canonical_phone,
    "imei": canonical_imei,
    "imsi": canonical_imsi,
    "upi": canonical_upi,
    "email": canonical_email,
    "ip": canonical_ip,
    "mac": canonical_mac,
    "domain": domain_of,
}


def canonical(kind: str, raw: object) -> Identifier | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    if kind in {"account", "account_masked"}:
        result = canonical_account(text)
        return Identifier(*result) if result else None
    func = _CANON.get(kind)
    if func is None:
        return Identifier(kind, text.lower() if kind in {"host", "cloud", "sender"} else text)
    value = func(text)
    return Identifier(kind, value) if value else None


def _schwa_delete(word: str) -> str:
    if len(word) > 2 and word.endswith("a") and word[-2] in _CONSONANT:
        return word[:-1]
    return word


def latin_name(raw: str) -> str:
    text = str(raw).strip()
    if _DEVANAGARI.search(text):
        hk = transliterate(text, sanscript.DEVANAGARI, sanscript.HK)
        words = [_schwa_delete(w) for w in hk.split()]
        text = " ".join(words)
        text = (
            text.replace("A", "a")
            .replace("I", "i")
            .replace("U", "u")
            .replace("M", "n")
            .replace("H", "h")
            .replace("R", "ri")
            .replace("z", "sh")
            .replace("S", "sh")
            .replace("G", "n")
            .replace("J", "n")
        )
    return text


def normalise_name(raw: str) -> str:
    text = latin_name(raw).lower()
    text = re.sub(r"[^a-z ]+", " ", text)
    words = [w for w in text.split() if w and w not in _HONORIFICS]
    return " ".join(words)


def name_similarity(a: str, b: str) -> float:
    left, right = normalise_name(a), normalise_name(b)
    if not left or not right:
        return 0.0
    return float(fuzz.token_set_ratio(left, right)) / 100.0


def address_similarity(a: str, b: str) -> float:
    left = re.sub(r"[^a-z0-9 ]+", " ", str(a).lower())
    right = re.sub(r"[^a-z0-9 ]+", " ", str(b).lower())
    if not left.strip() or not right.strip():
        return 0.0
    return float(fuzz.token_set_ratio(left, right)) / 100.0


def display(entity: str) -> str:
    kind, _, value = entity.partition(":")
    if kind == "account" and value.count(":") == 1:
        ifsc, number = value.split(":")
        return f"{ifsc} {number}"
    return value


def kind_of(entity: str) -> str:
    return entity.partition(":")[0]
