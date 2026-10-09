"""Live IBKR account state via ib_async - cash/net-liq/position snapshot for order sizing.

Mirrors the connect pattern in optiontrading/voo_options_automation.py. Adds
reqAccountSummary-based cash/net-liquidation lookup, which the option-trading
scripts don't currently use (they only read positions()).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from ib_async import IB

from newstrading.common import usd_summary_value
from newstrading.models.order_recommendation import AccountSnapshot

PAPER_PORT = 7497
LIVE_PORT = 7496


@contextmanager
def connect(host: str = "127.0.0.1", live: bool = False, client_id: int = 21) -> Iterator[IB]:
    ib = IB()
    port = LIVE_PORT if live else PAPER_PORT
    ib.connect(host, port, clientId=client_id)
    try:
        yield ib
    finally:
        if ib.isConnected():
            ib.disconnect()


def get_account_snapshot(ib: IB, symbol: str) -> AccountSnapshot:
    rows = ib.accountSummary()
    cash = usd_summary_value(rows, "TotalCashValue")
    net_liq = usd_summary_value(rows, "NetLiquidation", cash)
    gross_position_value = usd_summary_value(rows, "GrossPositionValue")

    existing_qty = 0
    positions = ib.positions()
    open_position_count = 0
    for position in positions:
        contract = position.contract
        if contract.secType == "STK" and position.position:
            open_position_count += 1
        if contract.symbol == symbol and contract.secType == "STK":
            existing_qty += int(position.position)

    return AccountSnapshot(
        cash=cash,
        net_liquidation=net_liq,
        existing_position_qty=existing_qty,
        open_position_count=open_position_count,
        gross_position_value=gross_position_value,
    )
