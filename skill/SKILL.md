---
name: defi-yield-monitor
description: Monitor DeFi lending & savings positions across Aave v3, SparkLend, Spark Savings, and Kamino. Track balances, APY, health factors, and compute 7d/30d yield. Use when user asks to check DeFi positions, lending yields, stablecoin earnings, portfolio health, or wants automated DeFi reporting. Triggers: "check my DeFi", "lending yield", "DeFi收益", "持仓", "APY", "health factor", "stablecoin yield", "Aave positions", "Spark savings", "Kamino".
---

# DeFi Yield Monitor

Cross-chain DeFi lending & savings monitor. No API keys required — all data from public endpoints.

## Setup

```bash
cd <skill_dir>/../   # project root (parent of skill/)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.json config/config.json
```

Edit `config/config.json`: add wallet addresses and enable desired protocols.

### Config Structure

```json
{
  "wallets": {
    "evm": ["0x..."],
    "solana": ["So1..."]
  },
  "protocols": [
    { "chain": "eth", "name": "aave" },
    { "chain": "eth", "name": "spark_savings" },
    { "chain": "solana", "name": "kamino" }
  ],
  "thresholds": {
    "min_health_factor": 1.25,
    "max_daily_drawdown_pct": 5
  }
}
```

## Commands

All commands run from the project root (parent of `skill/`).

### Daily Report (positions + risk alerts)

```bash
python main.py --config config/config.json
```

### Yield Summary (7d/30d PnL + APY)

```bash
python main.py --config config/config.json --yield-summary
```

### JSON Output (programmatic)

```bash
python main.py --config config/config.json --json
```

## Proxy Requirement

If running behind a firewall (e.g. China), detect proxy port first:

```bash
/usr/sbin/lsof -nP | grep quickqser | grep LISTEN   # or your proxy
export https_proxy=http://127.0.0.1:<port>
export http_proxy=http://127.0.0.1:<port>
```

DefiLlama and Aave GraphQL endpoints require internet access.

## Automated Snapshots

Set up a cron job (or OpenClaw cron) to collect snapshots twice daily. After 7 days of data, `--yield-summary` shows actual realized returns.

### OpenClaw Cron Example

```
Schedule: "13 9,21 * * *" (Asia/Shanghai)
Command: cd <project_root> && python main.py --config config/config.json --yield-summary
```

## Supported Protocols

| Protocol | Chain | Data Source |
|----------|-------|------------|
| Aave v3 | ETH, BSC | GraphQL API |
| SparkLend | ETH, Base | On-chain RPC |
| Spark Savings | ETH | DefiLlama + ERC-4626 on-chain |
| Kamino | Solana | Kamino Public API |

## Output Fields

Each position includes: `chain`, `protocol`, `wallet`, `supplied_usd`, `borrowed_usd`, `net_value_usd`, `apy_supply`, `apy_borrow`, `health_factor`, `timestamp`.

Yield summary includes: current APY per protocol, 7d/30d PnL (absolute + percentage), annualized APY from actual returns.

## Interpreting Results

- **Health factor < threshold** → risk alert, consider repaying debt
- **APY = 0** for a protocol → APY data unavailable (usually SparkLend borrow/supply rate)
- **Insufficient data** for 7d/30d → keep collecting snapshots, data will accumulate

## Source

GitHub: https://github.com/reed1898/defi-yield-monitor
