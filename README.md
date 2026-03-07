# defi-yield-monitor

First usable version of a cross-chain DeFi lending monitor.

## What works in this phase

- Aave positions via public GraphQL (`api.v3.aave.com`) on ETH + BSC
- Kamino obligations via public API (`api.kamino.finance`) on Solana
- Spark adapter wired in with graceful degradation (public wallet endpoint is unstable/undocumented)
- Unified data model output:
  - `chain/protocol/wallet/supplied_usd/borrowed_usd/net_value_usd/apy_supply/apy_borrow/health_factor/rewards_usd_24h/timestamp`
- Aggregation report:
  - total assets / debt / net value
  - 24h / 7d PnL (marked `insufficient history` until snapshots accumulate)
- Config-driven multi-wallet + multi-protocol + thresholds
- Text daily report template suitable for upstream push sessions

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

```bash
cp config/config.example.json config/config.json
```

Edit `config/config.json` with your wallets and protocols. No API key is required for this phase.

## Run

```bash
python main.py --config config/config.json
python main.py --config config/config.json --json
```

## Data sources

- Aave: `https://api.v3.aave.com/graphql`
- Kamino: `https://api.kamino.finance/v2/kamino-market` and user obligations endpoints
- Spark: currently attempts known public endpoints under `https://api-v2.spark.fi/api/v1/...`; logs warning and skips when unavailable

## Notes on degradation and logs

- Each adapter logs warnings when endpoint/network/data parsing fails.
- Failures are isolated per wallet/protocol; the whole run continues.
- Spark currently degrades to warning-only if no public wallet endpoint is reachable.

## Snapshot and PnL behavior

- Snapshot path is controlled by `snapshot_path`.
- The monitor stores rolling history (`last 60 points`) to compute 24h/7d PnL.
- If baseline is missing, report explicitly shows `insufficient history`.

## Project structure

- `adapters/`: protocol fetchers
- `core/`: normalization + aggregation
- `storage/`: snapshot persistence
- `reports/`: daily text renderer

## Security

- Do not commit private keys or RPC secrets.
- This phase uses only public endpoints and wallet addresses.
