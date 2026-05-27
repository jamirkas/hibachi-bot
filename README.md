# 🥩 Hibachi Trading Bot

Grid trading + Market Making bot for [Hibachi](https://hibachi.xyz) — a privacy-first perpetuals DEX with **0% maker fees**.

Every round-trip bid/ask is pure spread profit. No taker fees on maker orders.

## Features

- **Grid Strategy** — ladder of buy/sell limit orders around mid-price
- **Market Making** — bid/ask spread capture with adaptive width
- **Close Mode** — auto-reduce exposure when position exceeds threshold (inspired by [zo-market-maker-ts](https://github.com/yat1ma30/zo-market-maker-ts))
- **Binance Oracle** — optional Binance WebSocket fair price (avoids manipulated order books)
- **Web Dashboard** — real-time PnL chart, positions, orders, event log
- **Docker** — one-command deploy with docker-compose
- **Setup Wizard** — interactive config for non-technical users
- **Risk Management** — TP/SL, max exposure, cancel on sharp moves

## Quick Start

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Run setup wizard (creates .env + config.yaml)
python setup.py

# 3. Run bot
python main.py                    # Grid strategy (default)
python main.py --strategy mm      # Market maker only
python main.py --strategy grid,mm # Both
```

Dashboard: `http://localhost:8080` (when enabled in config)

## Docker

```bash
# Run grid + mm in separate containers
docker compose up -d

# Or combined in one container
docker compose --profile combined up -d
```

## Configuration

| File | Purpose |
|------|---------|
| `.env` | API keys (HIBACHI_API_KEY, HIBACHI_SECRET_KEY, HIBACHI_ACCOUNT_ID) |
| `config.yaml` | Trading parameters (strategy, spread, risk, etc.) |

**Security:** API keys go in `.env` — never in `config.yaml`. `.env` is gitignored.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `HIBACHI_API_KEY` | ✅ | — | API key from Hibachi Settings |
| `HIBACHI_SECRET_KEY` | ✅ | — | Secret key from Hibachi Settings |
| `HIBACHI_ACCOUNT_ID` | ✅ | — | Account ID from Hibachi Settings |
| `DASHBOARD_PORT` | ❌ | `8080` | Web dashboard port |
| `DASHBOARD_TOKEN` | ❌ | — | Dashboard auth token (empty = no auth) |
| `DASHBOARD_HOST` | ❌ | `127.0.0.1` | Dashboard bind address |
| `BINANCE_ORACLE_ENABLED` | ❌ | `0` | Set to `1` for Binance fair price |

## Strategies

### Grid Trading
Places N buy levels below mid-price and N sell levels above. Fills are tracked for TP/SL. All levels filled → grid resets.

```
        SELL @ mid + 3*step
        SELL @ mid + 2*step
        SELL @ mid + 1*step
 ─────── MID ───────
        BUY  @ mid - 1*step
        BUY  @ mid - 2*step
        BUY  @ mid - 3*step
```

### Market Making
Maintains bid/ask orders around mid-price. Spread auto-adjusts to volatility. Position limits prevent runaway exposure.

**Close Mode:** When long > `close_mode_threshold_usd`, stops buying — only sells to reduce. Vice versa for short. Tightens spread for faster unwind.

## Project Structure

```
hibachi_bot/
├── auth.py              # HMAC-SHA256 signing
├── exchange.py          # REST API wrapper
├── config.py            # Config loader + validation
├── dashboard.py         # FastAPI web dashboard
├── oracle.py            # Binance WebSocket fair price
├── risk.py              # Risk utilities
└── strategies/
    ├── base.py          # Abstract base
    ├── grid.py          # Grid trading
    └── mm.py            # Market making
main.py                  # Entry point
setup.py                 # Interactive wizard
```

## Security Review

- ✅ Secrets in `.env` (gitignored, never committed)
- ✅ Dashboard binds to `127.0.0.1` by default
- ✅ Optional dashboard token auth (`DASHBOARD_TOKEN`)
- ✅ `.env` permissions set to 600 by setup wizard
- ✅ Dependencies pinned to exact versions
- ✅ HMAC-SHA256 signing with timestamp + body hash

## Acknowledgements

- Review and improvements inspired by [zo-market-maker-ts](https://github.com/yat1ma30/zo-market-maker-ts) (127 ⭐)
- Security audit by Grok (xAI)
