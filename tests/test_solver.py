"""
Unit tests for solver.py (Convex LP optimizer, state price recovery, budget constraints).
"""
import unittest
from book import BookLevel
from solver import solve_combinatorial_arbitrage


class TestSolver(unittest.TestCase):
    def test_two_outcome_arbitrage(self):
        """Asks at 0.40 and 0.40 (sum=0.80) must trigger an arbitrage."""
        levels = [
            BookLevel(outcome_idx=0, price=0.40, quantity=100.0),
            BookLevel(outcome_idx=1, price=0.40, quantity=100.0),
        ]
        res = solve_combinatorial_arbitrage(
            num_outcomes=2,
            levels=levels,
            fee_per_contract=0.005,
            days_to_expiry=1.0,
        )
        self.assertTrue(res["arbitrage_found"])
        self.assertAlmostEqual(res["guaranteed_payout"], 100.0, places=2)
        # Cost: 100 * (0.40 + 0.005) * 2 = 81.0
        self.assertAlmostEqual(res["total_cost"], 81.0, places=2)
        self.assertAlmostEqual(res["net_profit"], 19.0, places=2)
        self.assertEqual(res["allocations"], [100.0, 100.0])

    def test_no_arbitrage_when_sum_exceeds_one(self):
        """Asks at 0.55 and 0.55 (sum=1.10) must reject arbitrage."""
        levels = [
            BookLevel(outcome_idx=0, price=0.55, quantity=100.0),
            BookLevel(outcome_idx=1, price=0.55, quantity=100.0),
        ]
        res = solve_combinatorial_arbitrage(num_outcomes=2, levels=levels)
        self.assertFalse(res["arbitrage_found"])
        self.assertEqual(res["net_profit"], 0.0)
        self.assertEqual(res["total_cost"], 0.0)
        self.assertEqual(res["allocations"], [0.0, 0.0])

    def test_missing_outcome_rejection(self):
        """If liquidity exists for only 1 of 2 outcomes, no hedge is possible."""
        levels = [
            BookLevel(outcome_idx=0, price=0.30, quantity=100.0),
        ]
        res = solve_combinatorial_arbitrage(num_outcomes=2, levels=levels)
        self.assertFalse(res["arbitrage_found"])
        self.assertEqual(res["guaranteed_payout"], 0.0)

    def test_budget_constraint_prioritizes_cheap_liquidity(self):
        """When budget is capped, solver must consume the 0.38 tier before the 0.46 tier."""
        levels = [
            BookLevel(outcome_idx=0, price=0.38, quantity=50.0),  # level 0
            BookLevel(outcome_idx=0, price=0.46, quantity=100.0), # level 1
            BookLevel(outcome_idx=1, price=0.38, quantity=50.0),  # level 2
            BookLevel(outcome_idx=1, price=0.46, quantity=100.0), # level 3
        ]
        # Fee is 0.005 -> eff price for 0.38 is 0.385.
        # Cost to buy all 50 cheap contracts is 50 * (0.385 + 0.385) = $38.50.
        res = solve_combinatorial_arbitrage(
            num_outcomes=2,
            levels=levels,
            fee_per_contract=0.005,
            max_capital=38.50,
        )
        self.assertTrue(res["arbitrage_found"])
        self.assertAlmostEqual(res["total_cost"], 38.50, places=2)
        # Should allocate 50 to level 0 & 2, and 0 to level 1 & 3
        self.assertAlmostEqual(res["allocations"][0], 50.0, places=2)
        self.assertAlmostEqual(res["allocations"][1], 0.0, places=2)
        self.assertAlmostEqual(res["allocations"][2], 50.0, places=2)
        self.assertAlmostEqual(res["allocations"][3], 0.0, places=2)

    def test_state_price_recovery(self):
        """Arrow-Debreu state prices must sum to ~1.0 (implied probability distribution)."""
        levels = [
            BookLevel(outcome_idx=0, price=0.30, quantity=100.0),
            BookLevel(outcome_idx=1, price=0.30, quantity=100.0),
            BookLevel(outcome_idx=2, price=0.30, quantity=100.0),
        ]
        res = solve_combinatorial_arbitrage(
            num_outcomes=3,
            levels=levels,
            fee_per_contract=0.005,
        )
        self.assertTrue(res["arbitrage_found"])
        state_prices = res.get("state_prices", [])
        self.assertEqual(len(state_prices), 3)
        self.assertAlmostEqual(sum(state_prices), 1.0, places=2)


if __name__ == "__main__":
    unittest.main()

