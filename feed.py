"""
feed.py: Real-world market data ingestion, Kalshi public API adapter,
order book parser, snapshot recorder, and historical replay engine.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import json
import os
import time
import urllib.request
import urllib.error

from book import OrderBook
from solver import solve_combinatorial_arbitrage
from backtest import BacktestConfig, simulate_execution


class KalshiPublicClient:
    """
    Client for unauthenticated public market data from Kalshi's v2 REST API.
    Does not require API keys or credentials for public L2 order book reads.
    """
    BASE_URL = os.getenv("KALSHI_API_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")

    def __init__(self, timeout_sec: float = 10.0):
        self.timeout_sec = timeout_sec

    def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "KalshiArbResearch/1.0 (Academic/Backtesting Engine)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Kalshi API HTTP {e.code}: {e.reason} ({url})") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to Kalshi API: {e.reason}") from e

    def get_mutually_exclusive_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves active events flagged with mutually_exclusive=True containing >= 2 markets.
        """
        data = self._get(f"/events?status=open&with_nested_markets=true&limit={limit}")
        events = data.get("events", [])
        return [
            e for e in events
            if e.get("mutually_exclusive") is True and len(e.get("markets", [])) >= 2
        ]

    def get_event(self, event_ticker: str) -> Dict[str, Any]:
        """Fetches full metadata and nested market tickers for a specific event."""
        data = self._get(f"/events/{event_ticker}?with_nested_markets=true")
        return data.get("event", {})

    def get_orderbook(self, market_ticker: str) -> Dict[str, Any]:
        """Fetches raw L2 order book depth for a specific contract ticker."""
        return self._get(f"/markets/{market_ticker}/orderbook")

    def get_event_orderbooks(self, event_ticker: str) -> Dict[str, Any]:
        """
        Fetches a synchronized snapshot of order books across all constituent
        markets of a mutually exclusive event.
        """
        event = self.get_event(event_ticker)
        markets = event.get("markets", [])
        if not markets:
            raise ValueError(f"Event {event_ticker} has no nested markets.")

        snapshot: Dict[str, Any] = {
            "timestamp": time.time(),
            "event_ticker": event_ticker,
            "event_title": event.get("title", ""),
            "markets": [],
        }

        for m in markets:
            ticker = m["ticker"]
            subtitle = m.get("yes_sub_title") or m.get("subtitle") or ticker
            ob_data = self.get_orderbook(ticker)
            snapshot["markets"].append({
                "ticker": ticker,
                "subtitle": subtitle,
                "orderbook": ob_data,
            })

        return snapshot


def parse_kalshi_orderbook(book: OrderBook, outcome_idx: int, ob_json: Dict[str, Any]) -> int:
    """
    Parses a Kalshi order book payload and converts resting orders into canonical YES ask liquidity.

    Kalshi Market Microstructure Identity:
      Kalshi's internal matching engine stores resting limit orders as bids.
      - A resting bid to buy NO at price p_no with quantity q is synthetically
        equivalent to an ASK to sell YES at (1.00 - p_no) with quantity q.
      - Therefore, any combinatorial basket buyer purchasing YES contracts across outcomes
        executes against resting NO bids (no_dollars) in Kalshi's book.

    Returns:
        Number of valid price levels added to the canonical book for this outcome.
    """
    levels_added = 0
    raw_ob = ob_json.get("orderbook", ob_json)

    # 1. Floating-point dollar representation (orderbook_fp)
    if "orderbook_fp" in raw_ob:
        fp = raw_ob["orderbook_fp"]
        # Resting NO bids -> Synthetic YES asks @ (1.00 - p_no)
        for level in fp.get("no_dollars", []):
            try:
                p_no = float(level[0])
                qty = float(level[1])
                if 0.0 < p_no < 1.0 and qty > 0:
                    book.add_synthetic_no_bid(outcome_idx, p_no, qty)
                    levels_added += 1
            except (ValueError, IndexError):
                continue

        # Resting YES asks (if exchange provides explicit YES ask tiers)
        for level in fp.get("yes_asks_dollars", []):
            try:
                p_yes = float(level[0])
                qty = float(level[1])
                if 0.0 < p_yes < 1.0 and qty > 0:
                    book.add_direct_yes_ask(outcome_idx, p_yes, qty)
                    levels_added += 1
            except (ValueError, IndexError):
                continue

    # 2. Legacy integer cent representation (orderbook with cent prices 1..99)
    elif "no" in raw_ob or "yes" in raw_ob:
        for level in raw_ob.get("no", []):
            try:
                p_no = float(level[0]) / 100.0
                qty = float(level[1])
                if 0.0 < p_no < 1.0 and qty > 0:
                    book.add_synthetic_no_bid(outcome_idx, p_no, qty)
                    levels_added += 1
            except (ValueError, IndexError):
                continue

        for level in raw_ob.get("yes_asks", []):
            try:
                p_yes = float(level[0]) / 100.0
                qty = float(level[1])
                if 0.0 < p_yes < 1.0 and qty > 0:
                    book.add_direct_yes_ask(outcome_idx, p_yes, qty)
                    levels_added += 1
            except (ValueError, IndexError):
                continue

    return levels_added


def record_event_snapshots(
    event_ticker: str,
    num_snapshots: int = 10,
    interval_sec: float = 1.0,
    output_path: str = "data/recorded_replay.jsonl",
) -> None:
    """
    Polls an active Kalshi event and writes time-series L2 order book snapshots to a JSONL file.
    """
    client = KalshiPublicClient()
    print(f"Recording {num_snapshots} snapshots for event '{event_ticker}' (interval: {interval_sec}s)...")

    with open(output_path, "w", encoding="utf-8") as f:
        for i in range(num_snapshots):
            try:
                snapshot = client.get_event_orderbooks(event_ticker)
                f.write(json.dumps(snapshot) + "\n")
                f.flush()
                print(f"  [Snapshot {i + 1}/{num_snapshots}] Captured {len(snapshot['markets'])} markets at {snapshot['timestamp']:.2f}")
            except Exception as e:
                print(f"  [Snapshot {i + 1}/{num_snapshots}] Error: {e}")

            if i < num_snapshots - 1:
                time.sleep(interval_sec)

    print(f"Recording complete. Output saved to {output_path}")


@dataclass
class ReplayTradeRecord:
    timestamp: float
    iso_time: str
    net_pnl: float
    capital_deployed: float
    guaranteed_payout: float
    aroc: float
    survival_prob: float
    state_prices: List[float]


class ReplayHarness:
    """
    Event-driven historical backtesting harness.
    Replays a sequence of recorded L2 market snapshots, solves for combinatorial arbitrage,
    and applies execution realism (queue priority haircuts & latency decay).
    """
    def __init__(
        self,
        replay_file_path: str,
        config: Optional[BacktestConfig] = None,
        capital_cap: Optional[float] = 1000.0,
    ):
        self.replay_file_path = replay_file_path
        self.config = config or BacktestConfig()
        self.capital_cap = capital_cap
        self.trade_log: List[ReplayTradeRecord] = []
        self.total_snapshots_processed: int = 0
        self.opportunities_detected: int = 0

    def run(self) -> Dict[str, Any]:
        """
        Executes the tick-by-tick replay through the historical snapshot dataset.
        """
        self.trade_log.clear()
        self.total_snapshots_processed = 0
        self.opportunities_detected = 0

        with open(self.replay_file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue

                snapshot = json.loads(line)
                self.total_snapshots_processed += 1
                ts = snapshot.get("timestamp", float(line_idx))
                iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))

                markets = snapshot.get("markets", [])
                num_outcomes = len(markets)
                if num_outcomes < 2:
                    continue

                book = OrderBook(num_outcomes=num_outcomes)
                for outcome_idx, m_data in enumerate(markets):
                    ob = m_data.get("orderbook", {})
                    parse_kalshi_orderbook(book, outcome_idx, ob)

                canonical_asks = book.get_canonical_asks()
                if not canonical_asks:
                    continue

                # Run realistic simulated execution with latency and queue haircut
                sim = simulate_execution(
                    levels=canonical_asks,
                    num_outcomes=num_outcomes,
                    config=self.config,
                    capital_cap=self.capital_cap,
                )

                if sim["executed"] and sim["net_pnl"] > 1e-4:
                    self.opportunities_detected += 1
                    self.trade_log.append(
                        ReplayTradeRecord(
                            timestamp=ts,
                            iso_time=iso_time,
                            net_pnl=sim["net_pnl"],
                            capital_deployed=sim["capital_deployed"],
                            guaranteed_payout=sim["guaranteed_payout"],
                            aroc=sim["aroc"],
                            survival_prob=sim["survival_prob"],
                            state_prices=sim.get("state_prices", []),
                        )
                    )

        return self.get_summary()

    def get_summary(self) -> Dict[str, Any]:
        """Calculates aggregated performance and risk metrics over the replay session."""
        total_pnl = sum(t.net_pnl for t in self.trade_log)
        total_capital = sum(t.capital_deployed for t in self.trade_log)
        avg_aroc = (
            sum(t.aroc for t in self.trade_log) / len(self.trade_log)
            if self.trade_log
            else 0.0
        )
        avg_survival = (
            sum(t.survival_prob for t in self.trade_log) / len(self.trade_log)
            if self.trade_log
            else 0.0
        )

        return {
            "total_snapshots": self.total_snapshots_processed,
            "opportunities_detected": self.opportunities_detected,
            "total_trades_executed": len(self.trade_log),
            "cumulative_pnl": round(total_pnl, 4),
            "total_capital_deployed": round(total_capital, 4),
            "average_aroc": round(avg_aroc, 4),
            "average_survival_prob": round(avg_survival, 4),
            "trade_records": [t.__dict__ for t in self.trade_log],
        }

    def print_report(self) -> None:
        """Prints a recruiter-grade performance and trade execution summary."""
        summary = self.get_summary()
        print("\n" + "=" * 76)
        print("  HISTORICAL ORDER BOOK REPLAY - EXECUTION REPORT")
        print("=" * 76)
        print(f"  Dataset:                 {self.replay_file_path}")
        print(f"  Snapshots Processed:     {summary['total_snapshots']}")
        print(f"  Opportunities Detected:  {summary['opportunities_detected']}")
        print(f"  Trades Executed:         {summary['total_trades_executed']}")
        print(f"  Execution Fill Rate:     {(summary['average_survival_prob'] * 100):.2f}% (Avg Latency Survival)")
        print(f"  Total Capital Deployed:  ${summary['total_capital_deployed']:,.2f}")
        print(f"  Cumulative Net PnL:      ${summary['cumulative_pnl']:,.2f}")
        print(f"  Average Realized AROC:   {summary['average_aroc']:.2f}x (Annualized)")
        print("-" * 76)

        if self.trade_log:
            print(f"  {'Timestamp':<20} | {'Deployed':>10} | {'Payout':>10} | {'Net PnL':>10} | {'AROC':>8}")
            print("  " + "-" * 68)
            for t in self.trade_log[:10]:
                print(
                    f"  {t.iso_time:<20} | "
                    f"${t.capital_deployed:>9.2f} | "
                    f"${t.guaranteed_payout:>9.2f} | "
                    f"${t.net_pnl:>9.2f} | "
                    f"{t.aroc:>7.2f}x"
                )
            if len(self.trade_log) > 10:
                print(f"  ... [{len(self.trade_log) - 10} additional trades logged]")
        else:
            print("  No executed trades during this session.")
        print("=" * 76 + "\n")

