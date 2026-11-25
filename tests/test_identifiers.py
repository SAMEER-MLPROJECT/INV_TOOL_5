from __future__ import annotations

import pytest

from sakshya.core.identifiers import (
    canonical,
    canonical_account,
    canonical_email,
    canonical_imei,
    canonical_ip,
    canonical_mac,
    canonical_phone,
    canonical_upi,
    display,
    domain_of,
    kind_of,
    latin_name,
    luhn_valid,
    name_similarity,
)


@pytest.mark.parametrize("raw", ["9876543210", "09876543210", "+91 98765 43210", "98765-43210", "919876543210"])
def test_indian_mobile_numbers_share_one_form(raw: str) -> None:
    assert canonical_phone(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["", "12345", "5876543210"])
def test_invalid_phone_numbers_are_rejected(raw: str) -> None:
    assert canonical_phone(raw) is None


def test_imei_check_digit() -> None:
    assert luhn_valid("352099001761481")
    assert not luhn_valid("352099001761482")
    assert canonical_imei("35-209900-176148") == "352099001761481"
    assert canonical_imei("35-209900-176148-1") == "352099001761481"


@pytest.mark.parametrize("raw", ["IVBK0323115:4742217245142", "ivbk0323115 / 4742217245142", "IVBK0323115-4742217245142"])
def test_account_with_ifsc(raw: str) -> None:
    assert canonical_account(raw) == ("account", "IVBK0323115:4742217245142")


def test_account_without_ifsc_and_masked() -> None:
    assert canonical_account("4742217245142") == ("account", "UNKNOWN:4742217245142")
    assert canonical_account("XXXX5142") == ("account_masked", "5142")


def test_other_identifiers() -> None:
    assert canonical_upi(" Meera.Iyer@IVB ") == "meera.iyer@ivb"
    assert canonical_email(" A@B.test ") == "a@b.test"
    assert canonical_mac("3C-52-82-46-D5-3E") == "3c:52:82:46:d5:3e"
    assert canonical_ip("192.0.2.1") == "192.0.2.1"
    assert canonical_ip("999.1.1.1") is None
    assert domain_of("https://www.tradexprime.test/login?x=1") == "tradexprime.test"


def test_entities_and_display() -> None:
    identifier = canonical("phone", "+919516761222")
    assert identifier is not None and identifier.entity == "phone:+919516761222"
    assert kind_of("upi:x@y") == "upi"
    assert display("account:IVBK0323115:4742217245142") == "IVBK0323115 4742217245142"


def test_names_across_scripts() -> None:
    assert latin_name("रोहित कुमार") == "rohit kumar"
    assert name_similarity("रोहित कुमार", "Rohit Kumar") == pytest.approx(1.0)
    assert name_similarity("Rohit Kumar", "Sunil Verma") < 0.5
