"""
solver.py: Convex optimization (LP) engine using SciPy HiGHS.
Incorporates fee drag, AROC hurdle constraints, capital budget capping,
and Arrow-Debreu state price extraction.
"""
from typing import List, Dict, Any, Optional
import numpy as np
from scipy.optimize import linprog
from book import BookLevel


def solve_combinatorial_arbitrage(
    num_outcomes: int,
    levels: List[BookLevel],
    fee_per_contract: float = 0.005,
    days_to_expiry: float = 1.0,
    annual_hurdle_rate: float = 0.15,
    max_capital: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Finds the profit-maximizing arbitrage allocation across book depth using an LP epigraph formulation.

    Formulation:
        Decision vector z = [x_0, x_1, ..., x_{K-1}, t]^T
        where:
            x_k = contract allocation for order book level k (0 <= x_k <= quantity_k)
            t   = guaranteed minimum payout across all M outcomes (t >= 0)

        Objective:
            min  sum_k (price_k + fee) * x_k - t   (equivalently: max t - Cost)

        Subject to:
            1. Payout floor (M constraints, one per outcome m in 0..M-1):
               t <= sum_{k: outcome_k = m} x_k  ==>  t - sum_{k: outcome_k = m} x_k <= 0
            2. Hurdle rate constraint:
               (1 + r * tau) * Cost <= t         ==>  (1 + r * tau) * Cost - t <= 0
            3. Budget constraint (optional, when max_capital is specified):
               Cost <= max_capital               ==>  sum_k (price_k + fee) * x_k <= max_capital
    """
    K = len(levels)
    M = num_outcomes

    # Fast path: zero levels, zero outcomes, or non-positive budget
    if K == 0 or M == 0 or (max_capital is not None and max_capital <= 0):
        return {
            "arbitrage_found": False,
            "net_profit": 0.0,
            "guaranteed_payout": 0.0,
            "total_cost": 0.0,
            "allocations": [0.0] * K,
            "shadow_prices": [],
            "state_prices": [],
        }

    # An arbitrage across M mutually exclusive outcomes requires liquidity in all M outcomes.
    # If any outcome has 0 available orders, guaranteed payout t cannot exceed 0.
    outcomes_present = {lvl.outcome_idx for lvl in levels if 0 <= lvl.outcome_idx < M}
    if len(outcomes_present) < M:
        return {
            "arbitrage_found": False,
            "net_profit": 0.0,
            "guaranteed_payout": 0.0,
            "total_cost": 0.0,
            "allocations": [0.0] * K,
            "shadow_prices": [],
            "state_prices": [],
        }

    tau = max(days_to_expiry, 1e-4) / 365.0
    effective_prices = [lvl.price + fee_per_contract for lvl in levels]

    # Objective: Minimize cost - payout ==> Minimize sum(eff_p * x) - t
    f = effective_prices + [-1.0]

    # Constraints: M payout floors + 1 hurdle rate + (optional) 1 budget constraint
    num_constraints = M + 1 + (1 if max_capital is not None else 0)
    A_ub = np.zeros((num_constraints, K + 1))
    b_ub = np.zeros(num_constraints)

    # 1. Outcome payout constraints: t - sum_{k in outcome m} x_k <= 0
    for k, lvl in enumerate(levels):
        if 0 <= lvl.outcome_idx < M:
            A_ub[lvl.outcome_idx, k] = -1.0
    A_ub[:M, -1] = 1.0

    # 2. Hurdle rate constraint: (1 + r * tau) * sum(eff_p * x) - t <= 0
    hurdle_mult = 1.0 + (annual_hurdle_rate * tau)
    for k in range(K):
        A_ub[M, k] = hurdle_mult * effective_prices[k]
    A_ub[M, -1] = -1.0

    # 3. Capital budget constraint: sum(eff_p * x) <= max_capital
    if max_capital is not None:
        for k in range(K):
            A_ub[M + 1, k] = effective_prices[k]
        A_ub[M + 1, -1] = 0.0
        b_ub[M + 1] = float(max_capital)

    bounds = [(0.0, lvl.quantity) for lvl in levels] + [(0.0, None)]

    res = linprog(c=f, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

    if not res.success:
        return {
            "arbitrage_found": False,
            "net_profit": 0.0,
            "guaranteed_payout": 0.0,
            "total_cost": 0.0,
            "allocations": [0.0] * K,
            "shadow_prices": [],
            "state_prices": [],
        }

    allocations = res.x[:K]
    guaranteed_payout = float(res.x[-1])
    total_cost = float(sum(eff_p * qty for eff_p, qty in zip(effective_prices, allocations)))
    net_profit = float(guaranteed_payout - total_cost)

    has_arb = (net_profit > 1e-6) and (guaranteed_payout > 1e-6)

    # Extract dual variables (marginals)
    shadow_prices = (
        res.ineqlin.marginals.tolist()
        if hasattr(res, "ineqlin") and res.ineqlin is not None
        else []
    )
    # The first M shadow prices correspond to Arrow-Debreu state prices
    state_prices = [abs(float(p)) for p in shadow_prices[:M]] if shadow_prices else []

    if not has_arb:
        return {
            "arbitrage_found": False,
            "net_profit": 0.0,
            "guaranteed_payout": 0.0,
            "total_cost": 0.0,
            "allocations": [0.0] * K,
            "shadow_prices": shadow_prices,
            "state_prices": state_prices,
        }

    return {
        "arbitrage_found": True,
        "net_profit": round(net_profit, 6),
        "guaranteed_payout": round(guaranteed_payout, 6),
        "total_cost": round(total_cost, 6),
        "allocations": [round(float(q), 6) for q in allocations],
        "shadow_prices": shadow_prices,
        "state_prices": state_prices,
    }