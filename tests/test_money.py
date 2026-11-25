from __future__ import annotations

import pytest

from sakshya.money.flows import Statement, Transfer, trace

DAY = 86400.0
VICTIM = "account:IVBK0000001:100"
MULE = "account:IVBK0000002:200"
ONWARD = "account:NCBK0000003:300"


def _books() -> dict[str, Statement]:
    return {
        account: Statement(account, "E01", [], opening, 0.0, 10 * DAY)
        for account, opening in ((VICTIM, 500000.0), (MULE, 10000.0), (ONWARD, 0.0))
    }


def _transfers() -> list[Transfer]:
    return [
        Transfer("t1", 5 * DAY, VICTIM, MULE, 100000.0, "UPI", "transfer"),
        Transfer("t2", 5 * DAY + 600, MULE, ONWARD, 99000.0, "IMPS", "transfer"),
        Transfer("t3", 5 * DAY + 3600, ONWARD, "cash:atm:ATM-1", 40000.0, "ATM", "cash", atm="atm:ATM-1"),
    ]


def test_money_is_followed_through_layers_into_cash() -> None:
    result = trace(_transfers(), _books(), [VICTIM], reference_t=6 * DAY)
    assert result.victim_out == pytest.approx(100000.0)
    assert set(result.accounts) == {MULE, ONWARD}
    assert result.accounts[MULE].hop == 1
    assert result.accounts[ONWARD].hop == 2
    assert result.accounts[ONWARD].tainted_cash == pytest.approx(40000.0 * 100000.0 / 110000.0, rel=1e-3)
    held = sum(info.tainted_held for info in result.accounts.values())
    cash = sum(info.tainted_cash for info in result.accounts.values())
    assert held + cash == pytest.approx(100000.0, abs=1.0)


def test_pro_rata_dilutes_and_fifo_keeps_own_money_first() -> None:
    pro = trace(_transfers(), _books(), [VICTIM], policy="pro_rata", reference_t=6 * DAY)
    fifo = trace(_transfers(), _books(), [VICTIM], policy="fifo", reference_t=6 * DAY)
    assert pro.accounts[ONWARD].tainted_in == pytest.approx(99000.0 * 100000.0 / 110000.0, rel=1e-3)
    assert fifo.accounts[ONWARD].tainted_in == pytest.approx(89000.0, rel=1e-3)


def test_trail_as_it_stood_at_a_time() -> None:
    early = trace(_transfers(), _books(), [VICTIM], as_of=5 * DAY + 60, reference_t=6 * DAY)
    assert set(early.accounts) == {MULE}
    assert early.accounts[MULE].tainted_held == pytest.approx(100000.0)


def test_long_standing_payees_are_not_treated_as_the_offence() -> None:
    history = [Transfer("t0", 0.5 * DAY, VICTIM, MULE, 2000.0, "UPI", "transfer")]
    result = trace(history + _transfers(), _books(), [VICTIM], new_payee_days=1.0, reference_t=6 * DAY)
    assert result.victim_out == 0.0
