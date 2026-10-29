"""
Unit tests for book.py (OrderBook, Canonical YES mapping, price aggregation).
"""
import unittest
from book import OrderBook, ContractType, Side, BookLevel


class TestOrderBook(unittest.TestCase):
    def test_direct_yes_ask(self):
        book = OrderBook(num_outcomes=2)
        book.add_direct_yes_ask(outcome_idx=0, price=0.40, quantity=50.0)
        asks = book.get_canonical_asks()
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].outcome_idx, 0)
        self.assertEqual(asks[0].price, 0.40)
        self.assertEqual(asks[0].quantity, 50.0)

    def test_synthetic_no_bid_mapping(self):
        """A NO bid at 0.65 must map to a canonical YES ask at 0.35."""
        book = OrderBook(num_outcomes=2)
        book.add_synthetic_no_bid(outcome_idx=1, no_bid_price=0.65, quantity=100.0)
        asks = book.get_canonical_asks()
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].outcome_idx, 1)
        self.assertAlmostEqual(asks[0].price, 0.35, places=4)
        self.assertEqual(asks[0].quantity, 100.0)

    def test_same_price_aggregation(self):
        """Direct YES ask at 0.40 and synthetic NO bid at 0.60 must aggregate."""
        book = OrderBook(num_outcomes=2)
        book.add_direct_yes_ask(outcome_idx=0, price=0.40, quantity=30.0)
        book.add_order(
            outcome_idx=0,
            contract_type=ContractType.NO,
            side=Side.BID,
            price=0.60,  # 1.0 - 0.60 = 0.40
            quantity=70.0,
        )
        asks = book.get_canonical_asks()
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0].price, 0.40)
        self.assertEqual(asks[0].quantity, 100.0)

    def test_deterministic_sorting(self):
        """Canonical asks must be sorted by outcome_idx then price."""
        book = OrderBook(num_outcomes=2)
        book.add_direct_yes_ask(outcome_idx=1, price=0.50, quantity=10.0)
        book.add_direct_yes_ask(outcome_idx=0, price=0.60, quantity=20.0)
        book.add_direct_yes_ask(outcome_idx=0, price=0.30, quantity=15.0)

        asks = book.get_canonical_asks()
        expected = [
            (0, 0.30),
            (0, 0.60),
            (1, 0.50),
        ]
        actual = [(lvl.outcome_idx, lvl.price) for lvl in asks]
        self.assertEqual(actual, expected)

    def test_validation_errors(self):
        book = OrderBook(num_outcomes=2)
        # Out-of-bounds outcome
        with self.assertRaises(ValueError):
            book.add_direct_yes_ask(outcome_idx=2, price=0.40, quantity=10.0)

        # Invalid prices (outside 0.0 .. 1.0)
        with self.assertRaises(ValueError):
            book.add_direct_yes_ask(outcome_idx=0, price=1.20, quantity=10.0)
        with self.assertRaises(ValueError):
            book.add_direct_yes_ask(outcome_idx=0, price=-0.10, quantity=10.0)

        # Invalid quantity
        with self.assertRaises(ValueError):
            book.add_direct_yes_ask(outcome_idx=0, price=0.50, quantity=-5.0)

        # Unsupported contract side (e.g., YES BID)
        with self.assertRaises(ValueError):
            book.add_order(0, ContractType.YES, Side.BID, 0.50, 10.0)


if __name__ == "__main__":
    unittest.main()

