"""
Unit tests for feed.py (Kalshi API orderbook parser and ReplayHarness).
"""
import unittest
import tempfile
import json
import os
from book import OrderBook
from feed import parse_kalshi_orderbook, ReplayHarness
from backtest import BacktestConfig


class TestFeed(unittest.TestCase):
    def test_parse_kalshi_orderbook_fp(self):
        """Test parsing Kalshi's modern orderbook_fp schema."""
        book = OrderBook(num_outcomes=2)
        mock_payload = {
            "orderbook_fp": {
                # Resting NO bids -> mapped to YES asks @ (1.00 - p_no)
                "no_dollars": [
                    ["0.6500", "50.00"],
                    ["0.6000", "100.00"],
                ],
                "yes_dollars": [
                    ["0.3000", "20.00"],
                ],
            }
        }
        levels_added = parse_kalshi_orderbook(book, outcome_idx=0, ob_json=mock_payload)
        self.assertEqual(levels_added, 2)

        asks = book.get_canonical_asks()
        self.assertEqual(len(asks), 2)
        # 1.0 - 0.65 = 0.35
        self.assertAlmostEqual(asks[0].price, 0.35, places=4)
        self.assertEqual(asks[0].quantity, 50.0)
        # 1.0 - 0.60 = 0.40
        self.assertAlmostEqual(asks[1].price, 0.40, places=4)
        self.assertEqual(asks[1].quantity, 100.0)

    def test_replay_harness_execution(self):
        """Test ReplayHarness execution over a temporary JSONL replay fixture."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".jsonl") as tmp:
            snap1 = {
                "timestamp": 1000.0,
                "event_ticker": "TEST-EVENT",
                "markets": [
                    {
                        "ticker": "TEST-M0",
                        "orderbook": {"orderbook_fp": {"no_dollars": [["0.6000", "100.00"]]}}
                    },
                    {
                        "ticker": "TEST-M1",
                        "orderbook": {"orderbook_fp": {"no_dollars": [["0.6000", "100.00"]]}}
                    }
                ]
            }
            tmp.write(json.dumps(snap1) + "\n")
            tmp_path = tmp.name

        try:
            cfg = BacktestConfig(latency_ms=10.0, half_life_ms=50.0, queue_haircut=1.0)
            harness = ReplayHarness(replay_file_path=tmp_path, config=cfg)
            summary = harness.run()

            self.assertEqual(summary["total_snapshots"], 1)
            self.assertEqual(summary["total_trades_executed"], 1)
            self.assertGreater(summary["cumulative_pnl"], 0.0)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()

