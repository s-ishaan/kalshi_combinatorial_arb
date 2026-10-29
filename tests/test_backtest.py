"""
Unit tests for backtest.py (Execution realism, queue haircuts, latency decay, capacity curves).
"""
import unittest
from book import BookLevel
from backtest import BacktestConfig, simulate_execution, generate_capacity_curve


class TestBacktest(unittest.TestCase):
    def test_latency_decay_and_haircut(self):
        """Verify survival probability and queue haircut math."""
        # 45ms latency with 45ms half-life -> survival prob = 0.50
        # 0.80 queue haircut -> effective fill factor = 0.50 * 0.80 = 0.40
        config = BacktestConfig(
            latency_ms=45.0,
            half_life_ms=45.0,
            queue_haircut=0.80,
            taker_fee=0.005,
            days_to_expiry=1.0,
        )
        levels = [
            BookLevel(outcome_idx=0, price=0.40, quantity=100.0),
            BookLevel(outcome_idx=1, price=0.40, quantity=100.0),
        ]
        res = simulate_execution(levels, 2, config)
        self.assertTrue(res["executed"])
        self.assertAlmostEqual(res["survival_prob"], 0.50, places=4)
        self.assertAlmostEqual(res["effective_fill_factor"], 0.40, places=4)
        # Quantity haircut: 100 * 0.40 = 40 contracts
        self.assertAlmostEqual(res["guaranteed_payout"], 40.0, places=2)

    def test_config_validation(self):
        # Negative latency
        with self.assertRaises(ValueError):
            BacktestConfig(latency_ms=-5.0)

        # Zero half-life
        with self.assertRaises(ValueError):
            BacktestConfig(half_life_ms=0.0)

        # Invalid queue haircut (outside 0..1)
        with self.assertRaises(ValueError):
            BacktestConfig(queue_haircut=1.5)

    def test_capacity_curve_marginal_decay(self):
        """As capital cap increases, marginal AROC must be monotonically non-increasing."""
        levels = [
            BookLevel(outcome_idx=0, price=0.38, quantity=30.0),
            BookLevel(outcome_idx=0, price=0.44, quantity=100.0),
            BookLevel(outcome_idx=1, price=0.38, quantity=30.0),
            BookLevel(outcome_idx=1, price=0.44, quantity=100.0),
        ]
        config = BacktestConfig(latency_ms=0.0, queue_haircut=1.0, days_to_expiry=1.0)
        caps = [15.0, 30.0, 75.0, 150.0]
        curve = generate_capacity_curve(levels, 2, config, caps)

        self.assertEqual(len(curve), 4)
        marginal_arocs = [step["marginal_aroc"] for step in curve]

        # The first step has highest marginal AROC, which then decays
        self.assertGreaterEqual(marginal_arocs[0], marginal_arocs[1])
        self.assertGreaterEqual(marginal_arocs[1], marginal_arocs[2])
        self.assertGreaterEqual(marginal_arocs[2], marginal_arocs[3])


if __name__ == "__main__":
    unittest.main()

