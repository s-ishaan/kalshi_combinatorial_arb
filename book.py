"""
book.py: Canonical Limit Order Book (L2) and synthetic contract mapping.
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Tuple


class Side(Enum):
    BID = "BID"
    ASK = "ASK"


class ContractType(Enum):
    YES = "YES"
    NO = "NO"


@dataclass
class OrderLevel:
    price: float      # in dollars, e.g., 0.35
    quantity: float   # available contracts


@dataclass
class BookLevel:
    outcome_idx: int  # outcome index 0, 1, ..., M-1
    price: float      # effective canonical ask price in dollars
    quantity: float   # available depth


class OrderBook:
    """
    Maintains raw L2 order book depth and converts liquidity into canonical YES ask space.
    Canonical identity: 1 YES + 1 NO == $1.00
    - A direct YES Ask at p is an Ask at p.
    - A direct NO Bid at p is synthetically equivalent to a YES Ask at (1.0 - p).
    """
    def __init__(self, num_outcomes: int):
        if num_outcomes <= 0:
            raise ValueError(f"num_outcomes must be positive, got {num_outcomes}")
        self.num_outcomes = num_outcomes
        # Internal aggregation mapping: (outcome_idx, price) -> cumulative_quantity
        self._canonical_asks: Dict[Tuple[int, float], float] = {}

    def add_order(
        self,
        outcome_idx: int,
        contract_type: ContractType,
        side: Side,
        price: float,
        quantity: float,
    ) -> None:
        """
        Ingests a raw order, validates inputs, transforms it into canonical YES ask space,
        and aggregates quantity at identical price levels.
        """
        if not (0 <= outcome_idx < self.num_outcomes):
            raise ValueError(
                f"outcome_idx {outcome_idx} out of valid range [0, {self.num_outcomes - 1}]"
            )
        if not (0.0 < price < 1.0):
            raise ValueError(f"Price {price} must be strictly between 0.0 and 1.0 dollars")
        if quantity <= 0:
            raise ValueError(f"Quantity {quantity} must be strictly positive")

        if contract_type == ContractType.YES and side == Side.ASK:
            canonical_price = round(price, 4)
        elif contract_type == ContractType.NO and side == Side.BID:
            canonical_price = round(1.0 - price, 4)
        else:
            raise ValueError(
                f"Arbitrage buying executes against ask liquidity. "
                f"Unsupported contract side: {contract_type.value} {side.value}. "
                f"Expected YES ASK or NO BID."
            )

        key = (outcome_idx, canonical_price)
        self._canonical_asks[key] = self._canonical_asks.get(key, 0.0) + quantity

    def add_direct_yes_ask(self, outcome_idx: int, price: float, quantity: float) -> None:
        """Convenience method for direct YES ask liquidity."""
        self.add_order(outcome_idx, ContractType.YES, Side.ASK, price, quantity)

    def add_synthetic_no_bid(self, outcome_idx: int, no_bid_price: float, quantity: float) -> None:
        """Convenience method for direct NO bid (synthetic YES ask) liquidity."""
        self.add_order(outcome_idx, ContractType.NO, Side.BID, no_bid_price, quantity)

    def get_canonical_asks(self) -> List[BookLevel]:
        """
        Returns all canonical YES asks sorted deterministically by (outcome_idx, price).
        Liquidity at the same price level for the same outcome is aggregated.
        """
        return [
            BookLevel(outcome_idx=outcome_idx, price=price, quantity=round(qty, 6))
            for (outcome_idx, price), qty in sorted(self._canonical_asks.items())
        ]