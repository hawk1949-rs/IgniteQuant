"""Domestic submit gate: closed session / rejected risk → no intent."""

from __future__ import annotations

from ignitequant.domain.enums import ReasonCode, RiskAction
from ignitequant.engine.runtime_bridge import (
    domestic_session_allows_orders,
    market_closed_reject_decision,
    may_submit_domestic_order,
)
from ignitequant.market.session import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN


def test_domestic_session_allows_orders() -> None:
    assert domestic_session_allows_orders(TRADE_STATUS_OPEN) is True
    assert domestic_session_allows_orders(TRADE_STATUS_CLOSED) is False
    assert domestic_session_allows_orders("CLOSED") is False


def test_may_submit_rejects_when_closed() -> None:
    ok, hits = may_submit_domestic_order(trade_status=TRADE_STATUS_CLOSED)
    assert ok is False
    assert ReasonCode.MARKET_CLOSED.value in hits


def test_may_submit_rejects_when_pretrade_reject() -> None:
    pre = market_closed_reject_decision(
        decision_id="boot-flat:x:1",
        net_position=1,
        requested_position=0,
    )
    assert pre.action is RiskAction.REJECT
    ok, hits = may_submit_domestic_order(
        trade_status=TRADE_STATUS_OPEN,
        pretrade=pre,
    )
    assert ok is False
    assert ReasonCode.MARKET_CLOSED.value in hits


def test_may_submit_allows_open_without_pretrade() -> None:
    ok, hits = may_submit_domestic_order(trade_status=TRADE_STATUS_OPEN)
    assert ok is True
    assert hits == ()
