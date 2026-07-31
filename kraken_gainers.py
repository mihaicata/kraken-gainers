"""
Fetch the top 24h % gainers on Kraken (USD-quoted pairs) and store them as JSON.

Runs on a schedule via GitHub Actions (see .github/workflows/gainers.yml),
every 4 hours, committing each run's results to data/gainers.json.

Uses Kraken's public REST API (no API key needed):
  - GET /0/public/AssetPairs  -> list of tradable pairs
  - GET /0/public/Ticker      -> today's open ("o") and last trade price ("c"[0])

% change = (last - open) / open * 100

Requires: requests (pip install -r requirements.txt)
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import requests

API_BASE = "https://api.kraken.com/0/public"
DATA_FILE = Path(__file__).with_name("data") / "gainers.json"
CHUNK_SIZE = 50  # keep Ticker request URLs short
MAX_HISTORY = 500  # cap file growth; drop oldest runs beyond this


def get_usd_pairs() -> list[str]:
    """Return Kraken pair names quoted in USD (spot, non-dark-pool)."""
    resp = requests.get(f"{API_BASE}/AssetPairs", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data["error"]:
        raise RuntimeError(data["error"])

    pairs = []
    for name, info in data["result"].items():
        if name.endswith(".d"):  # dark pool pairs
            continue
        if info.get("quote") in ("ZUSD", "USD"):
            pairs.append(name)
    return pairs


def fetch_tickers(pairs: list[str]) -> dict[str, dict]:
    """Fetch ticker info for the given pairs, chunked to keep URLs short."""
    tickers: dict[str, dict] = {}
    for i in range(0, len(pairs), CHUNK_SIZE):
        chunk = pairs[i : i + CHUNK_SIZE]
        resp = requests.get(
            f"{API_BASE}/Ticker", params={"pair": ",".join(chunk)}, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if data["error"]:
            raise RuntimeError(data["error"])
        tickers.update(data["result"])
    return tickers


def compute_gainers(tickers: dict[str, dict]) -> list[dict]:
    """Return [{pair, pct_change_24h, last_price}] sorted highest gain first."""
    results = []
    for pair, info in tickers.items():
        open_price = float(info["o"])
        last_price = float(info["c"][0])
        if open_price <= 0:
            continue
        pct_change = (last_price - open_price) / open_price * 100
        results.append(
            {"pair": pair, "pct_change_24h": round(pct_change, 4), "last_price": last_price}
        )
    return sorted(results, key=lambda r: r["pct_change_24h"], reverse=True)


def top_gainers(n: int = 10) -> list[dict]:
    pairs = get_usd_pairs()
    tickers = fetch_tickers(pairs)
    return compute_gainers(tickers)[:n]


def save_run(gainers: list[dict]) -> dict:
    """Append this run to data/gainers.json (JSON array of runs) and return it."""
    run = {
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "gainers": gainers,
    }

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if DATA_FILE.exists():
        history = json.loads(DATA_FILE.read_text())

    history.append(run)
    history = history[-MAX_HISTORY:]
    DATA_FILE.write_text(json.dumps(history, indent=2) + "\n")
    return run


def main(n: int = 10) -> None:
    gainers = top_gainers(n)
    run = save_run(gainers)
    print(f"[{run['timestamp_utc']}] Top {n} Kraken USD gainers (24h):")
    for rank, g in enumerate(gainers, start=1):
        print(f"  {rank:2d}. {g['pair']:<12} {g['pct_change_24h']:+7.2f}%   last={g['last_price']}")


if __name__ == "__main__":
    main()
