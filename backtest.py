"""
backtest.py: Execution realism, queue priority haircut, latency decay,
and capacity curve generation.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from book import BookLevel
from solver import solve_combinatorial_arbitrage


@dataclass
class BacktestConfig:
    latency_ms: float = 30.0         # One-way wire + order processing delay
    half_life_ms: float = 45.0       # Empirical arbitrage decay half-life
    queue_haircut: float = 0.70      # Fill rate haircut for competing flow at front-of-queue
    taker_fee: float = 0.005         # Exchange fee per contract (e.g., $0.005 on Kalshi)
    days_to_expiry: float = 2.0      # Horizon to contract settlement
    annual_hurdle_rate: float = 0.15 # Minimum required annualized return (15%)

    def __post_init__(self):
        if self.latency_ms < 0:
            raise ValueError(f"latency_ms cannot be negative, got {self.latency_ms}")
        if self.half_life_ms <= 0:
            raise ValueError(f"half_life_ms must be strictly positive, got {self.half_life_ms}")
        if not (0.0 <= self.queue_haircut <= 1.0):
            raise ValueError(f"queue_haircut must be in [0.0, 1.0], got {self.queue_haircut}")
        if self.taker_fee < 0:
            raise ValueError(f"taker_fee cannot be negative, got {self.taker_fee}")
        if self.days_to_expiry <= 0:
            raise ValueError(f"days_to_expiry must be positive, got {self.days_to_expiry}")


def simulate_execution(
    levels: List[BookLevel],
    num_outcomes: int,
    config: BacktestConfig,
    capital_cap: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Simulates realistic market order execution under latency and adverse queue competition.

    1. Decay Model:
       Survival probability P(alive) = 0.5 ** (latency_ms / half_life_ms)
    2. Effective Depth:
       Haircut quantity = raw_quantity * P(alive) * queue_haircut
    3. Optimal Execution:
       Passes capital_cap directly into the LP solver to consume the most profitable
       book depth first, accurately modeling diminishing returns across book levels.
    """
    decay_factor = 0.5 ** (config.latency_ms / config.half_life_ms)
    effective_factor = decay_factor * config.queue_haircut

    # Haircut applied strictly to volume depth, never price coordinates
    haircut_levels = [
        BookLevel(
            outcome_idx=lvl.outcome_idx,
            price=lvl.price,
            quantity=round(lvl.quantity * effective_factor, 6),
        )
        for lvl in levels
    ]

    result = solve_combinatorial_arbitrage(
        num_outcomes=num_outcomes,
        levels=haircut_levels,
        fee_per_contract=config.taker_fee,
        days_to_expiry=config.days_to_expiry,
        annual_hurdle_rate=config.annual_hurdle_rate,
        max_capital=capital_cap,
    )

    if not result["arbitrage_found"]:
        return {
            "executed": False,
            "net_pnl": 0.0,
            "capital_deployed": 0.0,
            "guaranteed_payout": 0.0,
            "aroc": 0.0,
            "allocations": [0.0] * len(levels),
            "state_prices": result.get("state_prices", []),
            "survival_prob": round(float(decay_factor), 6),
            "effective_fill_factor": round(float(effective_factor), 6),
        }

    capital_deployed = result["total_cost"]
    net_pnl = result["net_profit"]
    tau_years = max(config.days_to_expiry, 1e-4) / 365.0

    # Annualized Return on Capital (AROC)
    aroc = (net_pnl / capital_deployed) / tau_years if capital_deployed > 0 else 0.0

    return {
        "executed": True,
        "net_pnl": round(float(net_pnl), 4),
        "capital_deployed": round(float(capital_deployed), 4),
        "guaranteed_payout": round(float(result["guaranteed_payout"]), 4),
        "aroc": round(float(aroc), 4),
        "allocations": result["allocations"],
        "state_prices": result.get("state_prices", []),
        "survival_prob": round(float(decay_factor), 4),
        "effective_fill_factor": round(float(effective_factor), 4),
    }


def generate_capacity_curve(
    levels: List[BookLevel],
    num_outcomes: int,
    config: BacktestConfig,
    capital_steps: List[float],
) -> List[Dict[str, Any]]:
    """
    Computes capital capacity and market impact curve across discrete capital limits.
    Demonstrates marginal return decay as capital sweeps through deeper order book levels.
    """
    curve = []
    prev_deployed = 0.0
    prev_pnl = 0.0
    tau_years = max(config.days_to_expiry, 1e-4) / 365.0

    for cap in sorted(capital_steps):
        sim = simulate_execution(levels, num_outcomes, config, capital_cap=cap)

        delta_cap = sim["capital_deployed"] - prev_deployed
        delta_pnl = sim["net_pnl"] - prev_pnl

        # Marginal AROC on incremental capital deployed
        marginal_aroc = (delta_pnl / delta_cap) / tau_years if delta_cap > 1e-4 else 0.0

        curve.append({
            "capital_cap": cap,
            "capital_deployed": sim["capital_deployed"],
            "net_pnl": sim["net_pnl"],
            "aroc": sim["aroc"],
            "marginal_aroc": round(marginal_aroc, 4),
            "executed": sim["executed"],
        })

        if sim["executed"]:
            prev_deployed = sim["capital_deployed"]
            prev_pnl = sim["net_pnl"]

    return curve