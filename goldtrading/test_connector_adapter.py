import unittest
from datetime import date, timedelta

from goldtrading.config import GoldConfig
from goldtrading.connector_adapter import (
    account_state_from_connector,
    build_calendar_spread_instructions,
    futures_quote_from_connector,
    select_mgc_future_contract,
    select_near_far_contracts,
    spot_quote_from_connector,
)
from goldtrading.models import CalendarRecommendation, FuturesQuote


def _ymd(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).strftime("%Y%m%d")


# Shaped like the real search_contracts("MGC") response fetched live this
# session: multiple unrelated instruments share the symbol "MGC".
SEARCH_CONTRACTS_MGC = [
    {"underlying_contract_id": 79702479, "exchange": "COMEX", "symbol": "MGC", "description": "E-Micro Gold ", "sections": [{"security_type": "IND"}, {"security_type": "BAG"}, {"security_type": "FOP"}, {"security_type": "FUT"}]},
    {"underlying_contract_id": 47640024, "exchange": "ARCA", "symbol": "MGC", "description": "VNGRD MRNGSTR MG CAP ETF-USD", "country_code": "US", "sections": [{"security_type": "STK"}, {"security_type": "BAG"}, {"security_type": "CFD"}, {"security_type": "OPT"}]},
    {"underlying_contract_id": 75098427, "exchange": "FWB", "symbol": "MGC", "description": "MGIC INVESTMENT CORP", "country_code": "DE", "sections": [{"security_type": "STK"}]},
]


class SelectMgcFutureContractTests(unittest.TestCase):
    def test_picks_the_comex_future_not_the_arca_etf(self):
        contract = select_mgc_future_contract(SEARCH_CONTRACTS_MGC, GoldConfig())
        self.assertEqual(contract["underlying_contract_id"], 79702479)
        self.assertEqual(contract["exchange"], "COMEX")

    def test_raises_when_no_match(self):
        with self.assertRaises(ValueError):
            select_mgc_future_contract([row for row in SEARCH_CONTRACTS_MGC if row["exchange"] != "COMEX"], GoldConfig())

    def test_raises_when_ambiguous(self):
        duplicated = SEARCH_CONTRACTS_MGC + [dict(SEARCH_CONTRACTS_MGC[0])]
        with self.assertRaises(ValueError):
            select_mgc_future_contract(duplicated, GoldConfig())


class SelectNearFarContractsTests(unittest.TestCase):
    def test_picks_near_and_far_respecting_config_gaps(self):
        config = GoldConfig()
        contracts = [
            {"contract_id_ex": "1@COMEX", "exchange": "COMEX", "symbol": "MGCV6", "last_trading_date": _ymd(2), "contract_month": "202601"},  # too soon
            {"contract_id_ex": "2@COMEX", "exchange": "COMEX", "symbol": "MGCZ6", "last_trading_date": _ymd(20), "contract_month": "202602"},  # near
            {"contract_id_ex": "3@COMEX", "exchange": "COMEX", "symbol": "MGCG7", "last_trading_date": _ymd(35), "contract_month": "202603"},  # too close to near
            {"contract_id_ex": "4@COMEX", "exchange": "COMEX", "symbol": "MGCJ7", "last_trading_date": _ymd(80), "contract_month": "202604"},  # far
        ]
        near, far = select_near_far_contracts(contracts, config)
        self.assertEqual(near["contract_id_ex"], "2@COMEX")
        self.assertEqual(far["contract_id_ex"], "4@COMEX")

    def test_unsorted_input_is_still_handled(self):
        config = GoldConfig()
        contracts = [
            {"contract_id_ex": "4@COMEX", "last_trading_date": _ymd(80), "contract_month": "202604"},
            {"contract_id_ex": "2@COMEX", "last_trading_date": _ymd(20), "contract_month": "202602"},
        ]
        near, far = select_near_far_contracts(contracts, config)
        self.assertEqual(near["contract_id_ex"], "2@COMEX")
        self.assertEqual(far["contract_id_ex"], "4@COMEX")

    def test_returns_none_near_when_nothing_clears_the_minimum_dte(self):
        config = GoldConfig()
        contracts = [{"contract_id_ex": "1@COMEX", "last_trading_date": _ymd(1), "contract_month": "202601"}]
        near, far = select_near_far_contracts(contracts, config)
        self.assertIsNone(near)
        self.assertIsNone(far)

    def test_returns_none_far_when_no_contract_is_far_enough_out(self):
        config = GoldConfig()
        contracts = [{"contract_id_ex": "1@COMEX", "last_trading_date": _ymd(20), "contract_month": "202601"}]
        near, far = select_near_far_contracts(contracts, config)
        self.assertIsNotNone(near)
        self.assertIsNone(far)


class QuoteConversionTests(unittest.TestCase):
    def test_futures_quote_from_connector_reads_hyphenated_bid_ask(self):
        contract_row = {"symbol": "MGCZ6", "last_trading_date": _ymd(50)}
        snapshot = {"bid-ask": {"bid": 2010.1, "ask": 2010.3}}
        quote = futures_quote_from_connector(contract_row, snapshot)
        self.assertEqual(quote.bid, 2010.1)
        self.assertEqual(quote.ask, 2010.3)
        self.assertEqual(quote.min_tick, 0.10)
        self.assertEqual(quote.days_to_expiry, 50)

    def test_futures_quote_from_connector_handles_empty_snapshot(self):
        contract_row = {"symbol": "MGCZ6", "last_trading_date": _ymd(50)}
        quote = futures_quote_from_connector(contract_row, {})
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.ask)
        self.assertIsNone(quote.mid_price)

    def test_spot_quote_from_connector_handles_empty_snapshot(self):
        # Matches the live get_price_snapshot({}) result observed for XAUUSD
        # this session -- inconclusive whether that's a data-entitlement gap
        # or just no current quote, so this must degrade cleanly either way.
        quote = spot_quote_from_connector({}, "XAUUSD")
        self.assertIsNone(quote.bid)
        self.assertIsNone(quote.mid_price)

    def test_spot_quote_from_connector_reads_a_live_quote(self):
        quote = spot_quote_from_connector({"bid-ask": {"bid": 2000.5, "ask": 2000.9}}, "XAUUSD")
        self.assertEqual(quote.mid_price, 2000.7)


class AccountStateFromConnectorTests(unittest.TestCase):
    def test_prefers_usd_balance_row_when_present(self):
        # Shaped like the live get_account_summary response fetched this
        # session: the account's base currency was HKD, not USD.
        account_summary = {"currency": "HKD", "net_liquidation": 119996.35, "total_cash_value": 44917.17}
        account_balances = [{"currency": "HKD", "cash_balance": 44917.17}, {"currency": "USD", "cash_balance": 5750.0}]
        account = account_state_from_connector(account_summary, account_balances)
        self.assertEqual(account.cash, 5750.0)

    def test_falls_back_to_account_summary_when_no_usd_row(self):
        account_summary = {"currency": "HKD", "net_liquidation": 119996.35, "total_cash_value": 44917.17}
        account = account_state_from_connector(account_summary, account_balances=[{"currency": "HKD", "cash_balance": 44917.17}])
        self.assertEqual(account.cash, 44917.17)
        self.assertEqual(account.net_liquidation, 119996.35)

    def test_falls_back_when_no_balances_given_at_all(self):
        account_summary = {"currency": "USD", "net_liquidation": 100000.0, "total_cash_value": 50000.0}
        account = account_state_from_connector(account_summary)
        self.assertEqual(account.cash, 50000.0)
        self.assertEqual(account.net_liquidation, 100000.0)


class BuildCalendarSpreadInstructionsTests(unittest.TestCase):
    def _recommendation(self, action: str) -> CalendarRecommendation:
        near = FuturesQuote(symbol="MGC", local_symbol="MGCZ6", expiry=_ymd(30), bid=2009.9, ask=2010.1, days_to_expiry=30, min_tick=0.10)
        far = FuturesQuote(symbol="MGC", local_symbol="MGCG7", expiry=_ymd(120), bid=2059.9, ask=2060.1, days_to_expiry=120, min_tick=0.10)
        return CalendarRecommendation(
            action=action, contracts=1, near_future=near, far_future=far,
            market_spread=50.0, theoretical_spread=23.67, mispricing=26.33, net_edge_after_costs=25.33,
            reasons=["test"],
        )

    def test_sell_calendar_spread_buys_near_sells_far(self):
        legs = build_calendar_spread_instructions(self._recommendation("SELL_CALENDAR_SPREAD"), "111@COMEX", "222@COMEX")
        near_leg, far_leg = legs
        self.assertEqual(near_leg["contract_id_ex"], "111@COMEX")
        self.assertEqual(near_leg["side"], "BUY")
        self.assertEqual(far_leg["contract_id_ex"], "222@COMEX")
        self.assertEqual(far_leg["side"], "SELL")

    def test_buy_calendar_spread_sells_near_buys_far(self):
        legs = build_calendar_spread_instructions(self._recommendation("BUY_CALENDAR_SPREAD"), "111@COMEX", "222@COMEX")
        near_leg, far_leg = legs
        self.assertEqual(near_leg["side"], "SELL")
        self.assertEqual(far_leg["side"], "BUY")

    def test_rejects_a_hold_recommendation(self):
        with self.assertRaises(ValueError):
            build_calendar_spread_instructions(self._recommendation("HOLD"), "111@COMEX", "222@COMEX")


if __name__ == "__main__":
    unittest.main()
