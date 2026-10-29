"""
main.py: Unified CLI & Execution Engine for Prediction Market Combinatorial Arbitrage.

Supported Modes:
  1. --mode replay   (Default): Historical tick-by-tick order book replay using real-world Kalshi market depth.
  2. --mode live     : Real-time scanner pulling live mutually exclusive events from Kalshi's public API.
  3. --mode benchmark: Synthetic 3-outcome FOMC interest rate decision benchmark with depth capacity curve.
"""
import argparse
import sys
from typing import Optional

from book import OrderBook, ContractType, Side
from solver import solve_combinatorial_arbitrage
from backtest import BacktestConfig, simulate_execution, generate_capacity_curve
from feed import KalshiPublicClient, ReplayHarness, parse_kalshi_orderbook


def run_benchmark() -> None:
    """Runs the 5-stage FOMC simulation benchmark with capacity curves."""
    print("=" * 76)
    print("  PREDICTION MARKET COMBINATORIAL ARBITRAGE ENGINE - BENCHMARK RUN")
    print("=" * 76)

    outcome_labels = {
        0: "Fed Cut >= 50 bps",
        1: "Fed Cut 25 bps",
        2: "Pause / Hike",
    }
    num_outcomes = len(outcome_labels)

    print(f"\n[1] Initializing L2 Order Book for {num_outcomes} Mutually Exclusive Outcomes:")
    for idx, label in outcome_labels.items():
        print(f"    Outcome {idx}: {label}")

    book = OrderBook(num_outcomes=num_outcomes)

    # Outcome 0:
    book.add_direct_yes_ask(outcome_idx=0, price=0.18, quantity=150.0)
    book.add_direct_yes_ask(outcome_idx=0, price=0.22, quantity=300.0)

    # Outcome 1: Direct YES Ask + Synthetic YES Ask (NO Bid @ 0.52 -> YES Ask @ 0.48)
    book.add_direct_yes_ask(outcome_idx=1, price=0.48, quantity=200.0)
    book.add_order(
        outcome_idx=1,
        contract_type=ContractType.NO,
        side=Side.BID,
        price=0.52,
        quantity=100.0,
    )
    book.add_direct_yes_ask(outcome_idx=1, price=0.54, quantity=400.0)

    # Outcome 2:
    book.add_direct_yes_ask(outcome_idx=2, price=0.24, quantity=250.0)
    book.add_synthetic_no_bid(outcome_idx=2, no_bid_price=0.72, quantity=350.0)

    canonical_asks = book.get_canonical_asks()
    print("\n[2] Aggregated Canonical YES Ask Liquidity:")
    print(f"    {'Outcome':<22} | {'Price':<8} | {'Depth (Contracts)':<18}")
    print("    " + "-" * 54)
    for lvl in canonical_asks:
        label = outcome_labels[lvl.outcome_idx]
        print(f"    {label:<22} | ${lvl.price:<7.2f} | {lvl.quantity:<18.1f}")

    top_prices = [
        min(lvl.price for lvl in canonical_asks if lvl.outcome_idx == m)
        for m in range(num_outcomes)
    ]
    top_sum = sum(top_prices)
    print(f"\n    Top-of-Book Implied Sum: ${top_sum:.2f} (Synthetic discount: ${(1.0 - top_sum):.2f})")

    print("\n[3] Solving Combinatorial Arbitrage (HiGHS LP Solver):")
    days_to_expiry = 2.0
    hurdle_rate = 0.15

    solver_res = solve_combinatorial_arbitrage(
        num_outcomes=num_outcomes,
        levels=canonical_asks,
        fee_per_contract=0.005,
        days_to_expiry=days_to_expiry,
        annual_hurdle_rate=hurdle_rate,
    )

    if not solver_res["arbitrage_found"]:
        print("    [!] No risk-free arbitrage satisfying hurdle rate found.")
        return

    print("    Arbitrage Detected:     YES")
    print(f"    Gross Guaranteed Payout: ${solver_res['guaranteed_payout']:,.2f}")
    print(f"    Total Acquisition Cost:  ${solver_res['total_cost']:,.2f} (including fees)")
    print(f"    Net Risk-Free Profit:    ${solver_res['net_profit']:,.2f}")

    print("\n    Extracted Arrow-Debreu State Prices (Implied Risk-Neutral Probabilities):")
    for m, prob in enumerate(solver_res["state_prices"]):
        print(f"      P({outcome_labels[m]}): {prob * 100:.2f}%")
    print(f"      Total Probability Mass: {sum(solver_res['state_prices']) * 100:.2f}%")

    print("\n[4] Simulating Realistic Execution Under Latency & Queue Competition:")
    config = BacktestConfig(
        latency_ms=25.0,
        half_life_ms=45.0,
        queue_haircut=0.75,
        taker_fee=0.005,
        days_to_expiry=days_to_expiry,
        annual_hurdle_rate=hurdle_rate,
    )

    sim_res = simulate_execution(
        levels=canonical_asks,
        num_outcomes=num_outcomes,
        config=config,
    )

    print(f"    Execution Survival Prob: {sim_res['survival_prob'] * 100:.2f}%  (Half-life: {config.half_life_ms}ms, Delay: {config.latency_ms}ms)")
    print(f"    Effective Fill Factor:   {sim_res['effective_fill_factor'] * 100:.2f}% (Queue Haircut: {config.queue_haircut * 100:.0f}%)")
    print(f"    Realized Capital Deployed: ${sim_res['capital_deployed']:,.2f}")
    print(f"    Realized Net PnL:          ${sim_res['net_pnl']:,.2f}")
    print(f"    Annualized Return (AROC):   {sim_res['aroc']:.2f}x (Annualized across {days_to_expiry} days)")

    print("\n[5] Capital Capacity Curve & Market Impact Analysis:")
    capital_brackets = [25.0, 50.0, 75.0, 100.0, 150.0, 250.0]
    curve = generate_capacity_curve(
        levels=canonical_asks,
        num_outcomes=num_outcomes,
        config=config,
        capital_steps=capital_brackets,
    )

    print(f"    {'Budget Cap':>10} | {'Deployed':>10} | {'Net PnL':>10} | {'AROC':>9} | {'Marginal AROC':>14}")
    print("    " + "-" * 62)
    for row in curve:
        print(
            f"    ${row['capital_cap']:9.2f} | "
            f"${row['capital_deployed']:9.2f} | "
            f"${row['net_pnl']:9.2f} | "
            f"{row['aroc']:8.2f}x | "
            f"{row['marginal_aroc']:13.2f}x"
        )

    print("\n" + "=" * 76)
    print("  SIMULATION RUN COMPLETED SUCCESSFULLY")
    print("=" * 76)


def run_replay(file_path: str = "data/kalshi_replay_sp500.jsonl") -> None:
    """Executes tick-by-tick event replay over recorded Kalshi market depth."""
    print("=" * 76)
    print("  KALSHI REAL-WORLD MARKET DATA REPLAY ENGINE")
    print("=" * 76)
    print(f"  Source Dataset: {file_path}")

    config = BacktestConfig(
        latency_ms=25.0,
        half_life_ms=45.0,
        queue_haircut=0.75,
        taker_fee=0.005,
        days_to_expiry=1.0,
        annual_hurdle_rate=0.15,
    )

    harness = ReplayHarness(replay_file_path=file_path, config=config, capital_cap=500.0)
    harness.run()
    harness.print_report()


def run_live_scanner(limit: int = 5) -> None:
    """Scans active mutually exclusive events directly from Kalshi's public API."""
    print("=" * 76)
    print("  KALSHI LIVE MARKET SCANNER (PUBLIC UNIFIED FEED)")
    print("=" * 76)

    client = KalshiPublicClient()
    try:
        events = client.get_mutually_exclusive_events(limit=limit)
    except Exception as e:
        print(f"[!] Error connecting to Kalshi API: {e}")
        return

    print(f"Discovered {len(events)} active mutually exclusive events:\n")

    for idx, e in enumerate(events, 1):
        ticker = e["event_ticker"]
        title = e.get("title", ticker)
        markets = e.get("markets", [])
        print(f"[{idx}] {ticker}: {title}")
        print(f"    Constituent Markets: {len(markets)}")

        # Build canonical book
        book = OrderBook(num_outcomes=len(markets))
        for outcome_idx, m in enumerate(markets):
            try:
                ob = client.get_orderbook(m["ticker"])
                parse_kalshi_orderbook(book, outcome_idx, ob)
            except Exception:
                continue

        canonical_asks = book.get_canonical_asks()
        if not canonical_asks:
            print("    [Depth]: No resting liquidity found in book.")
            print("-" * 76)
            continue

        # Check outcomes present
        outcomes_covered = len({lvl.outcome_idx for lvl in canonical_asks})
        print(f"    [Depth]: {len(canonical_asks)} price levels across {outcomes_covered}/{len(markets)} outcomes.")

        if outcomes_covered == len(markets):
            res = solve_combinatorial_arbitrage(
                num_outcomes=len(markets),
                levels=canonical_asks,
                fee_per_contract=0.005,
                days_to_expiry=7.0,
            )
            if res["arbitrage_found"]:
                print(f"    *** LIVE ARBITRAGE FOUND! ***")
                print(f"    Gross Payout: ${res['guaranteed_payout']:,.2f} | Cost: ${res['total_cost']:,.2f} | Net Profit: ${res['net_profit']:,.2f}")
            else:
                top_sum = sum(
                    min(lvl.price for lvl in canonical_asks if lvl.outcome_idx == m)
                    for m in range(len(markets))
                )
                print(f"    Top-of-Book Implied Sum: ${top_sum:.4f} (No discount currently)")
        else:
            print("    [Info]: Incomplete outcome coverage; risk-free basket unavailable.")
        print("-" * 76)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prediction Market Combinatorial Arbitrage Engine & Real-World Replay Harness"
    )
    parser.add_argument(
        "--mode",
        choices=["replay", "live", "benchmark"],
        default="replay",
        help="Execution mode: 'replay' (real historical Kalshi replay), 'live' (live API scanner), 'benchmark' (synthetic FOMC 3-bracket test)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/kalshi_replay_sp500.jsonl",
        help="Path to replay dataset file (for --mode replay)",
    )
    args = parser.parse_args()

    if args.mode == "replay":
        run_replay(args.dataset)
    elif args.mode == "live":
        run_live_scanner()
    elif args.mode == "benchmark":
        run_benchmark()


if __name__ == "__main__":
    main()
