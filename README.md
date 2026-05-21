# Hibachi Trading Bot

Grid trading + Market making bot for [Hibachi](https://hibachi.xyz) — privacy-first perpetual futures exchange.

## Features

- **Grid Trading** — place ladder of limit orders, profit from volatility
- **Market Making** — maintain bid/ask spread, earn 0% maker fees
- **Switchable** — toggle between strategies without restart
- **Risk Management** — configurable position sizing, stop-loss, max exposure

## Why Hibachi?

| Feature | Value |
|---|---|
| Maker fee | **0% on all tiers** |
| API | REST + WebSocket |
| Settlement | USDT (Arbitrum) |
| Markets | BTC, ETH, SOL |

## Quick Start

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml with your API keys
python main.py --strategy grid
```

## Configuration

See `config.example.yaml` for all options.

## License

MIT
