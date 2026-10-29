# Prediction Market Combinatorial Arbitrage Engine

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests: passing](https://img.shields.io/badge/tests-15%2F15%20passing-brightgreen.svg)]()

A high-performance quantitative trading engine and historical replay harness designed for **event contract combinatorial arbitrage** across mutually exclusive, collectively exhaustive prediction markets (e.g., Kalshi, Polymarket).

Features a **canonical L2 Limit Order Book normalizer**, a **convex linear programming (HiGHS) allocation solver** with capital hurdle constraints and Arrow-Debreu state price recovery, and an **execution realism simulator** modeling latency decay ($0.5^{\Delta t / t_{1/2}}$), queue priority haircuts, and diminishing marginal AROC across book depth.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────────────┐
                      │             Kalshi Public REST Feed          │
                      │   (api.elections.kalshi.com/trade-api/v2)    │
                      └──────────────────────┬───────────────────────┘
                                             │
                       ┌─────────────────────┴─────────────────────┐
                       ▼                                           ▼
             [Mode: --mode live]                        [Mode: --mode replay]
          Live Event Poller & Scanner             Historical L2 Tick-by-Tick Replay
                       │                                           │
                       └─────────────────────┬─────────────────────┘
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              feed.py (Parser)                │
                      │  Maps resting NO bids (no_dollars) into      │
                      │  synthetic YES asks @ (1.00 - p_no)          │
                      └──────────────────────┬───────────────────────┘
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │              book.py (OrderBook)             │
                      │  - L2 order book aggregation                 │
                      │  - Same-price depth consolidation            │
                      └──────────────────────┬───────────────────────┘
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │             solver.py (HiGHS LP)             │
                      │  - Payout floor epigraph constraints         │
                      │  - Cost-of-capital hurdle rate (r * tau)     │
                      │  - Budget capacity constraint                │
                      │  - Arrow-Debreu state price extraction       │
                      └──────────────────────┬───────────────────────┘
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │           backtest.py (Simulator)            │
                      │  - Latency half-life decay: 0.5^(dt / t_half)│
                      │  - Queue position fill haircut               │
                      │  - Concave Capacity Curve & Marginal AROC    │
                      └──────────────────────────────────────────────┘
```

---

## Quantitative Foundations

### 1. Market Microstructure & Contract Duality
In binary prediction markets, complementary contracts satisfy:
$$\text{Payoff}(\text{YES}) + \text{Payoff}(\text{NO}) \equiv \$1.00$$

On Kalshi, resting limit orders are held entirely as bids. A resting bid to buy NO at price $p_{\text{no}}$ with quantity $q$ is equivalent to an offer to sell YES at:
$$p_{\text{yes}}^{\text{synthetic}} = 1.00 - p_{\text{no}}$$

For an event with $M$ mutually exclusive and collectively exhaustive outcomes $m \in \{0, 1, \dots, M-1\}$, a risk-free arbitrage exists if a basket of 1 YES contract across all $M$ outcomes can be acquired for less than $\$1.00$ net of taker fees:
$$\sum_{m=0}^{M-1} \min \left( p_{m, \text{ask}} + \text{fee} \right) < 1.00$$

### 2. Convex Optimization Formulation (Linear Program)
When order books have multi-tiered depth and non-uniform volume, the optimal contract allocations are solved via an epigraph LP.

**Decision Vector:**
$$z = \begin{bmatrix} x_0 & x_1 & \dots & x_{K-1} & t \end{bmatrix}^T$$
where $x_k$ is the allocation for order book tier $k$, and $t$ is the guaranteed minimum gross payout across all outcomes.

**Objective:**
$$\min_{z} \quad \sum_{k=0}^{K-1} (p_k + \text{fee}) x_k - t \quad \iff \quad \max_{z} \quad \left( t - \text{Total Cost} \right)$$

**Subject to:**
1. **Payout Floors ($M$ outcome constraints):**
   $$t - \sum_{k \in \text{outcome } m} x_k \le 0 \quad \forall m \in \{0, \dots, M-1\}$$
2. **Annualized Return on Capital (AROC) Hurdle Constraint:**
   $$(1 + r \cdot \tau) \sum_{k=0}^{K-1} (p_k + \text{fee}) x_k - t \le 0$$
   where $r$ is the minimum required annual hurdle rate (e.g. 15%) and $\tau = \frac{\text{days to expiry}}{365}$.
3. **Capital Budget Constraint:**
   $$\sum_{k=0}^{K-1} (p_k + \text{fee}) x_k \le \text{Capital Cap}$$
4. **Volume Bounds:**
   $$0 \le x_k \le q_k, \quad t \ge 0$$

### 3. Arrow-Debreu State Prices
The dual variables (shadow prices) of the $M$ payout constraints, $\lambda_0, \dots, \lambda_{M-1}$, satisfy:
$$\lambda_m = \frac{\partial (\text{Profit})}{\partial (\text{Payout in state } m)}$$
In the absence of fee distortions, $|\lambda_m|$ recovers the **implied risk-neutral probability distribution** over the mutually exclusive outcome space ($\sum_{m=0}^{M-1} |\lambda_m| \approx 1.00$).

### 4. Execution Realism: Latency Decay & Queue Haircuts
Real arbitrage flow faces competing algorithmic latency. We model book fill probability using an exponential half-life decay function:
$$P(\text{survival}) = 0.5^{\frac{\Delta t_{\text{latency}}}{t_{1/2}}}$$
Combined with an adverse queue competition haircut $\kappa_{\text{queue}} \in (0, 1]$, effective executable depth is scaled:
$$q_k^{\text{effective}} = q_k \cdot P(\text{survival}) \cdot \kappa_{\text{queue}}$$

---

## Project Structure

```
kalshi/
├── book.py             # Canonical L2 Limit Order Book with synthetic contract mapping
├── solver.py           # SciPy HiGHS LP solver with epigraph & state price extraction
├── backtest.py         # Latency decay, queue haircut simulator & capacity curves
├── feed.py             # Kalshi unauthenticated REST client, parser & ReplayHarness
├── main.py             # Unified CLI runner (replay, live, and benchmark modes)
├── data/
│   └── kalshi_replay_sp500.jsonl  # Recorded 25-minute tick-by-tick Kalshi market depth
├── tests/
│   ├── test_book.py    # Order book mapping and aggregation tests
│   ├── test_solver.py  # LP constraints, budget capping, state price tests
│   ├── test_backtest.py# Latency decay and capacity curve monotonicity tests
│   └── test_feed.py    # Kalshi JSON parsing and replay harness tests
├── requirements.txt    # Project dependencies
└── README.md
```

---

## Quickstart

### Prerequisites
* Python 3.10+
* NumPy & SciPy

```bash
# Clone the repository
git clone https://github.com/your-username/kalshi-combinatorial-arb.git
cd kalshi-combinatorial-arb

# Install dependencies
pip install -r requirements.txt
```

### 1. Run Historical Event Replay (Default)
Replays a 25-minute tick-by-tick sequence of real-world Kalshi order book depth:
```bash
python3 main.py --mode replay
```

**Sample Output:**
```text
============================================================================
  HISTORICAL ORDER BOOK REPLAY - EXECUTION REPORT
============================================================================
  Dataset:                 data/kalshi_replay_sp500.jsonl
  Snapshots Processed:     25
  Opportunities Detected:  8
  Trades Executed:         8
  Execution Fill Rate:     68.04% (Avg Latency Survival)
  Total Capital Deployed:  $867.20
  Cumulative Net PnL:      $51.34
  Average Realized AROC:   21.11x (Annualized)
----------------------------------------------------------------------------
  Timestamp            |   Deployed |     Payout |    Net PnL |     AROC
  --------------------------------------------------------------------
  2024-10-30 15:05:00  | $   119.03 | $   127.57 | $     8.55 |   26.21x
  2024-10-30 15:06:00  | $   119.03 | $   127.57 | $     8.55 |   26.21x
  2024-10-30 15:07:00  | $   119.03 | $   127.57 | $     8.55 |   26.21x
  ...
============================================================================
```

### 2. Run Live Kalshi Scanner
Pulls live mutually exclusive events directly from Kalshi's public exchange API:
```bash
python3 main.py --mode live
```

### 3. Run Benchmark Simulation (Capacity Curve Analysis)
Simulates an FOMC rate decision market and prints the diminishing marginal returns curve:
```bash
python3 main.py --mode benchmark
```

**Capacity Curve Sample:**
```text
    Budget Cap |   Deployed |    Net PnL |      AROC |  Marginal AROC
    --------------------------------------------------------------
    $    25.00 | $    25.00 | $     2.32 |    16.95x |         16.95x
    $    50.00 | $    50.00 | $     4.64 |    16.95x |         16.95x
    $    75.00 | $    75.00 | $     6.74 |    16.40x |         15.30x
    $   100.00 | $   100.00 | $     7.92 |    14.45x |          8.60x
    $   150.00 | $   144.16 | $     8.93 |    11.31x |          4.18x
    $   250.00 | $   144.16 | $     8.93 |    11.31x |          0.00x
```

---

## Running Automated Tests

Run the full suite using Python's built-in `unittest` runner or `pytest`:

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

All 15 unit tests verify:
* Direct vs. synthetic contract mapping ($1.00 - p$).
* Price-level depth aggregation.
* LP optimization, budget capping, and missing-outcome rejection.
* Latency decay mathematical properties.
* Kalshi JSON order book parsing and replay harness execution.

---

## License
MIT License. Free for academic research, educational use, and portfolio inspection.
