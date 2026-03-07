# defi-yield-monitor

Cross-chain DeFi lending yield monitor with protocol adapters.

## Scope (v0)

- Ethereum/BSC: Aave, Spark
- Solana: Kamino
- Unified portfolio and yield reporting
- Daily report + threshold alerts

## Architecture

- `adapters/`: protocol-specific data collectors
- `core/`: normalization, aggregation, PnL logic
- `pricing/`: token pricing clients
- `storage/`: local snapshots for time-window comparisons
- `reports/`: report formatting
- `config/`: user config and thresholds

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.json config/config.json
python main.py --config config/config.json --json
```

## Output Metrics

- total_assets_usd
- total_debt_usd
- net_value_usd
- pnl_24h_usd
- pnl_7d_usd
- per-protocol breakdown
- risk flags (health factor and utilization thresholds)

## Roadmap

1. Implement Aave adapter (ETH/BSC)
2. Implement Spark adapter (ETH)
3. Implement Kamino adapter (Solana)
4. Add price fallback chain and alert daemon
