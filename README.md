# defi-yield-monitor

Cross-chain DeFi lending & savings yield monitor. Track positions, APY, and earnings across multiple protocols — no API keys required.

## Supported Protocols

| Protocol | Chain | Type | APY Source |
|----------|-------|------|------------|
| **Aave v3** | Ethereum, BSC | Lending | Aave GraphQL API |
| **Spark Savings** | Ethereum | Savings (ERC-4626) | DefiLlama Yields API |
| **SparkLend** | Ethereum, Base | Lending | On-chain RPC |
| **Kamino** | Solana | Lending | Kamino Public API |

## Features

- 📊 **Multi-protocol aggregation** — unified view across chains and protocols
- 📈 **Yield tracking** — 7-day and 30-day PnL with annualized APY calculation
- 🔔 **Risk alerts** — health factor monitoring with configurable thresholds
- 📸 **Historical snapshots** — rolling 180-point history with per-protocol breakdown
- 🌐 **No API keys** — all data from public endpoints and on-chain RPC

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

Edit `config/config.json` with your wallet addresses and enabled protocols.

## Usage

```bash
# Daily report with positions and risk alerts
python main.py --config config/config.json

# JSON output for programmatic use
python main.py --config config/config.json --json

# Yield/earnings summary (7d/30d PnL)
python main.py --config config/config.json --yield-summary
```

### Automated Daily Collection

Set up a cron job to collect snapshots twice daily. After ~7 days, the yield summary will show actual realized returns:

```bash
# Example crontab entry (twice daily)
13 9,21 * * * cd /path/to/defi-yield-monitor && python main.py --config config/config.json --text
```

## Data Sources

| Source | Endpoint | Used For |
|--------|----------|----------|
| Aave v3 GraphQL | `api.v3.aave.com` | Positions + APY |
| DefiLlama Yields | `yields.llama.fi/pools` | Spark Savings APY |
| Kamino API | `api.kamino.finance` | Solana lending positions |
| Ethereum RPC | Public nodes | Spark on-chain balances |

## Project Structure

```
adapters/        # Protocol-specific fetchers
  aave.py        # Aave v3 via GraphQL
  spark.py       # SparkLend + Spark Savings (ERC-4626)
  kamino.py       # Kamino on Solana
  defillama.py   # DefiLlama yields (supplementary APY)
core/            # Normalization + aggregation
storage/         # Snapshot persistence (rolling history)
reports/         # Text report + yield summary renderers
config/          # Configuration files
```

## Example Output

```
📊 Yield Summary

Current Net Value: $2,100,612.78

Current APY:
  ethereum:aave: 1.55% ($678,270.29)
  ethereum:spark_savings: 4.00% ($1,089,511.01)
  solana:kamino: 4.55% ($332,831.48)

7-Day Performance:
  PnL: +$1,234.56 (+0.06%)
  Annualized: 3.14%
```

## Security

- No private keys or API secrets needed — read-only public data only
- `config/config.json` and `storage/snapshots.json` are gitignored
- Wallet addresses are public by nature (blockchain transparency)

## OpenClaw Skill

This project includes an [OpenClaw](https://github.com/openclaw/openclaw) agent skill in the `skill/` directory. To use it with your OpenClaw agent:

1. Clone this repo to your agent's workspace
2. Install dependencies (`pip install -r requirements.txt`)
3. Copy `config/config.example.json` → `config/config.json` and add your wallets
4. Register the skill directory in your OpenClaw config:

```json
{
  "skills": {
    "entries": {
      "defi-yield-monitor": {
        "path": "/path/to/defi-yield-monitor/skill"
      }
    }
  }
}
```

Your agent can then monitor DeFi positions, check yields, and send automated reports.

## License

MIT

## Contributing

PRs welcome. If you want to add a new protocol adapter, check `adapters/aave.py` for the expected interface pattern.
