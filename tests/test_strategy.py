import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import scan


def signal_frame(highs=(100, 100, 100.01, 100)):
    index = pd.bdate_range("2024-01-01", periods=len(highs))
    return pd.DataFrame({
        "Open": 100.0, "High": highs, "Low": 99.0, "Close": 100.0,
        "atr": 1.0, "sig_ts": [False, True] + [False] * (len(highs) - 2),
        "sc_ts": [0, 7] + [0] * (len(highs) - 2), "screen1": True,
        "valid": True, "fi2": -1.0, "rsi2": 30.0, "w_hist_up": True,
        "screen2": False,
    }, index=index)


def trade(symbol, entry_date, exit_date, entry=100.0, exit=100.0,
          reason="open", risk=0.05, score=0.0):
    return scan.Trade(entry_date, exit_date, entry, exit,
                      exit / entry - 1 - scan.COST_RT, 1, reason, symbol, risk, score)


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.market = scan.MARKET_OK, scan.MARKET_CLOSE, scan.MARKET_LABEL

    def tearDown(self):
        scan.MARKET_OK, scan.MARKET_CLOSE, scan.MARKET_LABEL = self.market

    def test_buy_stop_triggers_on_exact_touch(self):
        _, last = scan.run_strategy(signal_frame(), scan.STRATEGIES["triple_screen"], "A")
        self.assertEqual(last["state"], "long")
        self.assertAlmostEqual(last["sim_entry"], 100.01)

    def test_missing_or_stale_market_blocks_signals(self):
        index = pd.bdate_range("2024-01-01", periods=3)
        scan.MARKET_OK = None
        self.assertFalse(scan.market_flags(index).any())
        scan.MARKET_OK = pd.Series([True], index=index[:1])
        self.assertEqual(scan.market_flags(index).tolist(), [True, False, False])

    def test_missing_spy_does_not_substitute_stock_basket(self):
        d = signal_frame()
        status = {"errors": []}
        scan.build_market({"A": d}, status)
        self.assertIsNone(scan.MARKET_CLOSE)
        self.assertFalse(scan.market_flags(d.index).any())

    def test_market_without_sma_history_remains_unknown(self):
        d = signal_frame()
        scan.build_market({"SPY": d}, {"errors": []})
        self.assertTrue(scan.MARKET_OK.isna().all())
        self.assertFalse(scan.market_flags(d.index).any())

    def test_pending_cancel_uses_previous_completed_market_day(self):
        d = signal_frame((100, 100, 100, 102))
        scan.MARKET_OK = pd.Series([True, True, False, False], index=d.index)
        _, last = scan.run_strategy(d, scan.STRATEGIES["triple_screen_rf"], "A")
        self.assertEqual(last["state"], "flat")
        # Today's negative close was not yet knowable when today's stop triggered.
        scan.MARKET_OK = pd.Series([True, True, True, False], index=d.index)
        _, last = scan.run_strategy(d, scan.STRATEGIES["triple_screen_rf"], "A")
        self.assertEqual(last["state"], "long")

    def test_pending_price_and_score_remain_from_pending_signal(self):
        # Fractional-cent historical bars: the old 99.01 trigger must not rise to 99.02.
        d = signal_frame((100, 100, 99, 99.009))
        d.loc[d.index[2:], ["Open", "Close"]] = 99
        row = scan.analyze("A", {}, d, "triple_screen")
        self.assertEqual(row["buy_stop"], 99.01)
        self.assertEqual(row["signal_score"], 7)

    def test_daily_size_is_integer_cash_and_symbol_capped(self):
        d = signal_frame()
        d.loc[d.index[-1], "sig_ts"] = True
        d.loc[d.index[-1], "atr"] = 0.01
        row = scan.analyze("A", {}, d, "triple_screen")
        self.assertLessEqual(row["shares_per_10k"] * row["ref_price"], 1000)
        self.assertIsInstance(row["shares_per_10k"], int)

    def test_ranking_uses_signal_score_and_stable_ticker(self):
        rows = [dict(ticker="B", signal_score=1, bt_win_rate_lb=.9, bt_payoff=9, bt_trades=99),
                dict(ticker="C", signal_score=2, bt_win_rate_lb=.1, bt_payoff=1, bt_trades=1),
                dict(ticker="A", signal_score=1, bt_win_rate_lb=.1, bt_payoff=1, bt_trades=1)]
        self.assertEqual([r["ticker"] for r in sorted(rows, key=scan.rank_key)], ["C", "A", "B"])

    def test_fixed_entry_atr_and_monotonic_trailing_stop(self):
        d = signal_frame((100, 100, 101, 105, 104))
        d["Open"] = [100, 100, 100, 104, 104]
        d["Low"] = [99, 99, 99, 103, 103.5]
        d["Close"] = [100, 100, 100, 104, 104]
        d["atr"] = [1, 1, 1, 20, 20]
        _, last = scan.run_strategy(d, scan.STRATEGIES["triple_screen"], "A")
        self.assertEqual(last["state"], "long")
        self.assertEqual(last["sim_stop"], 103)

    def test_bb_close_exit_is_next_open_and_atr_is_fixed(self):
        d = signal_frame((100,) * 5)
        d["sig_bb"] = [False, True, False, False, False]
        d["sc_bb"] = 1.0
        d["x_sma20"] = [False, False, False, True, False]
        d["atr"] = [1, 1, 20, 20, 20]
        d.loc[d.index[-1], "Open"] = 101
        trades, _ = scan.run_strategy(d, scan.STRATEGIES["bb_revert"], "A")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].reason, "cond")
        self.assertEqual(trades[0].exit_date, str(d.index[-1].date()))
        self.assertEqual(trades[0].risk, .03)

    def test_bb_time_exit_counts_entry_day_zero(self):
        d = signal_frame((100,) * 19)
        d["sig_bb"] = [False, True] + [False] * 17
        d["sc_bb"] = 1.0
        d["x_sma20"] = False
        trades, _ = scan.run_strategy(d, scan.STRATEGIES["bb_revert"], "A")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].reason, "time")
        self.assertEqual(trades[0].days, 16)

    def test_weekly_indicators_do_not_change_when_future_is_appended(self):
        index = pd.bdate_range("2022-01-03", periods=300)
        close = 100 + np.arange(300) * .1 + np.sin(np.arange(300))
        d = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                          "Close": close, "Volume": 1000}, index=index)
        full = scan.add_indicators(d)
        for n in (247, 249, 251):
            partial = scan.add_indicators(d.iloc[:n])
            pd.testing.assert_frame_equal(partial, full.iloc[:n])


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.market = scan.MARKET_OK, scan.MARKET_CLOSE, scan.MARKET_LABEL

    def tearDown(self):
        scan.MARKET_OK, scan.MARKET_CLOSE, scan.MARKET_LABEL = self.market

    def test_unclosed_position_only_pays_entry_fee_and_stays_invested(self):
        index = pd.bdate_range("2024-01-01", periods=3)
        closes = pd.DataFrame({"A": [100, 100, 100]}, index=index)
        result = scan.simulate_portfolio([trade("A", "2024-01-01", "2024-01-03")], closes, index[0])
        # $50 risk permits nine whole shares including prospective exit costs.
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 - 900 * scan.COST_RT / 2)
        self.assertEqual(result["metrics"]["avg_positions"], 1)

    def test_aggregate_initial_risk_limits_entries(self):
        index = pd.bdate_range("2024-01-01", periods=3)
        closes = pd.DataFrame({str(i): 100 for i in range(8)}, index=index)
        trades = [trade(str(i), "2024-01-01", "2024-01-03", risk=.1) for i in range(8)]
        result = scan.simulate_portfolio(trades, closes, index[0])
        self.assertLessEqual(result["metrics"]["max_planned_risk"], 200)
        self.assertLess(result["metrics"]["trades_taken"], 8)

    def test_intraday_exit_does_not_free_slot_for_morning_entry(self):
        index = pd.bdate_range("2024-01-01", periods=3)
        closes = pd.DataFrame({"A": 100, "B": 100}, index=index)
        for reason, expected in [("stop", 1), ("cond", 2), ("time", 2)]:
            with self.subTest(reason=reason):
                trades = [trade("A", "2024-01-01", "2024-01-02", reason=reason),
                          trade("B", "2024-01-02", "2024-01-03")]
                result = scan.simulate_portfolio(trades, closes, index[0], max_pos=1)
                self.assertEqual(result["metrics"]["trades_taken"], expected)

    def test_same_day_stop_does_not_reuse_slot(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({"A": 100, "B": 100}, index=index)
        trades = [trade("A", "2024-01-01", "2024-01-01", reason="stop", score=1),
                  trade("B", "2024-01-01", "2024-01-02", score=0)]
        result = scan.simulate_portfolio(trades, closes, index[0], max_pos=1)
        self.assertEqual(result["metrics"]["trades_taken"], 1)

    def test_small_affordable_position_is_not_rejected(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({"A": 400}, index=index)
        result = scan.simulate_portfolio([trade("A", "2024-01-01", "2024-01-02", entry=400, exit=400, risk=.1)], closes, index[0])
        self.assertEqual(result["metrics"]["trades_taken"], 1)

    def test_costs_cannot_overdraw_cash(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({str(i): 100 for i in range(10)}, index=index)
        trades = [trade(str(i), "2024-01-01", "2024-01-02", risk=.001) for i in range(10)]
        result = scan.simulate_portfolio(trades, closes, index[0])
        # 99 shares total; the final symbol cannot buy its tenth share plus fees.
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 - 9900 * scan.COST_RT / 2)

    def test_metrics_include_first_day_loss(self):
        eq = pd.Series([9900, 9900], index=pd.bdate_range("2024-01-01", periods=2))
        result = scan.curve_metrics(eq)
        self.assertAlmostEqual(result["max_dd"], -.01)
        self.assertAlmostEqual(result["yearly"]["2024"], -.01)
        self.assertLess(result["cagr"], 0)

    def test_known_opening_loss_reduces_new_entry_budget(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({"A": [100, 1], "B": [100, 200]}, index=index)
        trades = [trade("A", "2024-01-01", "2024-01-02", exit=1, reason="cond", risk=.001),
                  trade("B", "2024-01-02", "2024-01-02", entry=100, exit=200, risk=.099)]
        result = scan.simulate_portfolio(trades, closes, index[0])
        # After the known opening loss, B can buy four shares, not five.
        cash_after_exit = 10000 - 10 * 100 * 1.00025 + 10 * 1 * .99975
        expected = cash_after_exit - 4 * 100 * 1.00025 + 4 * 200
        self.assertAlmostEqual(result["equity"].iloc[-1], expected)

    def test_closed_trade_pays_both_actual_notional_fees(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({"A": [100, 110]}, index=index)
        result = scan.simulate_portfolio(
            [trade("A", "2024-01-01", "2024-01-02", exit=110, reason="cond")], closes, index[0])
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 - 9 * 100 * 1.00025 + 9 * 110 * .99975)

    def test_original_risk_is_not_released_after_price_rises(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({str(i): [100, 100] for i in range(6)}, index=index)
        closes.loc[:, [str(i) for i in range(4)]] = 110
        # Four positions use most of the aggregate budget; a later entry gets only residual risk.
        trades = [trade(str(i), "2024-01-01", "2024-01-02", risk=.05) for i in range(4)]
        trades.append(trade("4", "2024-01-02", "2024-01-02", risk=.05))
        result = scan.simulate_portfolio(trades, closes, index[0])
        # The gain increases equity, but original risk remains: only five new shares fit.
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 + 36 * 10 - 41 * 100 * .00025)

    def test_existing_risk_above_limit_does_not_force_sale_or_allow_new_risk(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({str(i): [10, 10] for i in range(4)}, index=index)
        closes["new"] = 100
        trades = [trade(str(i), "2024-01-01", "2024-01-02", risk=.05) for i in range(4)]
        trades.append(trade("new", "2024-01-02", "2024-01-02", risk=.05))
        result = scan.simulate_portfolio(trades, closes, index[0])
        self.assertEqual(result["metrics"]["trades_taken"], 4)
        self.assertEqual(result["metrics"]["avg_positions"], 4)
        self.assertGreater(result["metrics"]["max_planned_risk_pct"], .02)

    def test_intraday_exit_does_not_free_cash_with_spare_slots(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({str(i): 100 for i in range(11)}, index=index)
        trades = [trade(str(i), "2024-01-01", "2024-01-02", risk=.001,
                        reason="stop" if i == 0 else "open") for i in range(10)]
        trades.append(trade("10", "2024-01-02", "2024-01-02", risk=.001))
        result = scan.simulate_portfolio(trades, closes, index[0], max_pos=20)
        self.assertEqual(result["metrics"]["trades_taken"], 10)

    def test_momentum_uses_whole_shares_and_only_pays_actual_entry_fee(self):
        index = pd.bdate_range("2022-01-03", periods=300)
        prices = 100 + np.arange(300) * .1
        closes = pd.DataFrame({"A": prices}, index=index)
        result = scan.run_momentum(closes, closes.copy(), index[253], scan.STRATEGIES["mom_12_1_nf"])
        position = result["holdings"]["A"]
        self.assertIsInstance(position["shares_frac"], int)
        shares, entry = position["shares_frac"], position["entry"]
        self.assertLessEqual(shares * entry, 1000)
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 - shares * entry * 1.00025 + shares * prices[-1])

    def test_momentum_unknown_market_keeps_ranked_holdings_and_blocks_new_names(self):
        index = pd.bdate_range("2022-01-03", periods=320)
        rebalances = [i for i in scan.month_ends(index) if i >= 253]
        last_rebalance = rebalances[1]
        index = index[:last_rebalance + 3]
        closes = pd.DataFrame({"A": 100.0, "B": 100.0}, index=index)
        scan.MARKET_OK = pd.Series(True, index=index).drop(index[last_rebalance])
        def scores(c, k, elig):
            return pd.Series({"A": .2, "B": .1 if k >= last_rebalance else -1})
        with patch.object(scan, "momentum_scores", side_effect=scores):
            result = scan.run_momentum(closes, closes, index[253], scan.STRATEGIES["mom_12_1"], top_n=2)
        self.assertEqual(set(result["holdings"]), {"A"})
        self.assertEqual(result["trades"], [])
        scan.MARKET_OK.loc[index[last_rebalance]] = False
        with patch.object(scan, "momentum_scores", side_effect=scores):
            bearish = scan.run_momentum(closes, closes, index[253], scan.STRATEGIES["mom_12_1"], top_n=2)
        self.assertEqual(bearish["holdings"], {})
        self.assertEqual(len(bearish["trades"]), 1)

    def test_momentum_missing_open_defers_sale_without_retrying_missed_buy(self):
        index = pd.bdate_range("2022-01-03", periods=320)
        last_rebalance = [i for i in scan.month_ends(index) if i >= 253][1]
        index = index[:last_rebalance + 4]
        closes = pd.DataFrame({"A": 100.0, "B": 100.0}, index=index)
        opens = closes.copy()
        opens.loc[index[last_rebalance + 1:last_rebalance + 3], "A"] = np.nan
        opens.loc[index[last_rebalance + 3], "A"] = 95.0
        opens.loc[index[last_rebalance + 1], "B"] = np.nan
        def scores(c, k, elig):
            return pd.Series({"A": -.1, "B": .2}) if k >= last_rebalance else pd.Series({"A": .2, "B": -.1})
        with patch.object(scan, "momentum_scores", side_effect=scores):
            waiting = scan.run_momentum(closes.iloc[:-1], opens.iloc[:-1], index[253], scan.STRATEGIES["mom_12_1_nf"], top_n=1)
            result = scan.run_momentum(closes, opens, index[253], scan.STRATEGIES["mom_12_1_nf"], top_n=1)
        self.assertEqual(set(waiting["holdings"]), {"A"})
        self.assertEqual(waiting["pending_exits"], ["A"])
        self.assertEqual(waiting["trades"], [])
        self.assertEqual(result["holdings"], {})
        self.assertEqual(result["trades"][0].exit_date, str(index[-1].date()))
        self.assertEqual(result["trades"][0].exit, 95)
        self.assertEqual(result["metrics"]["trades_taken"], 1)
        self.assertAlmostEqual(result["equity"].iloc[-1], 10000 - 10 * 100 * 1.00025 + 10 * 95 * .99975)

    def test_single_day_metrics_include_loss(self):
        eq = pd.Series([9900], index=pd.DatetimeIndex(["2024-01-01"]))
        result = scan.curve_metrics(eq)
        self.assertEqual(result["final"], 9900)
        self.assertAlmostEqual(result["max_dd"], -.01)

    def test_custom_initial_equity_is_used(self):
        index = pd.bdate_range("2024-01-01", periods=2)
        closes = pd.DataFrame({"A": [100, 100]}, index=index)
        result = scan.simulate_portfolio([], closes, index[0], start_equity=20000)
        self.assertEqual(result["metrics"]["cagr"], 0)
        self.assertEqual(result["metrics"]["max_dd"], 0)


class OutputTests(unittest.TestCase):
    def test_daily_output_uses_research_rules_without_writing_files(self):
        d = signal_frame((100, 100, 99, 99.009))
        row = scan.analyze("A", {}, d, "triple_screen")
        texts = []
        with patch.object(scan.Path, "mkdir"), patch.object(scan.Path, "write_text", side_effect=lambda s, **k: texts.append(s)), patch.object(pd.DataFrame, "to_csv"):
            scan.write_outputs([row], [row], {"errors": [], "universe_size": 1}, "2024-01-04", "triple_screen")
        import json
        payload = json.loads(texts[0])
        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["out_of_sample_validated"])
        self.assertEqual(payload["implementation_version"], "2026-10-28-v1")
        self.assertIn("0.5%", payload["rules"]["sizing"])
        self.assertIn("信号强度", payload["rules"]["ranking"])
        self.assertIn("示例股数", texts[-1])

    def test_lab_payload_discloses_partial_membership_filter_without_writing_files(self):
        index = pd.bdate_range("2022-01-03", periods=300)
        close = 100 + np.arange(300) * .1 + np.sin(np.arange(300))
        prices = {"A": pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                                    "Close": close, "Volume": 1000}, index=index)}
        universe = pd.DataFrame([{"ticker": "A", "date_added": "2022-01-03"}])
        with patch.object(scan, "MARKET_OK", None), patch.object(scan, "MARKET_CLOSE", None), patch.object(scan.Path, "mkdir"), patch.object(scan.Path, "write_text"), patch.object(pd.DataFrame, "to_csv"):
            payload = scan.run_lab(universe, prices, {"errors": []})
        self.assertEqual(payload["implementation_version"], "2026-10-28-v1")
        self.assertFalse(payload["portfolio_rules"]["point_in_time"])
        self.assertTrue(payload["portfolio_rules"]["added_date_filter"])
        self.assertTrue(payload["portfolio_rules"]["survivorship_bias_remaining"])
        self.assertIsNone(payload["benchmark"])
        self.assertFalse(payload["out_of_sample_validated"])


if __name__ == "__main__":
    unittest.main()
