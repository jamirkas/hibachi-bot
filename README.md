# 🥩 Hibachi Trading Bot

Grid trading + market making bot for [Hibachi](https://hibachi.xyz) — privacy-first perpetual futures exchange.

## Why Hibachi?

| Feature | Value |
|---|---|
| **Maker fee** | 0% on ALL tiers |
| Taker fee | 0.020% – 0.045% |
| Settlement | USDT (Arbitrum) |
| Markets | BTC, ETH, SOL perpetuals |

With 0% maker fees, every bid/ask round-trip is pure spread profit.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/jamirkas/hibachi-bot
cd hibachi-bot

# 2. Install
pip install -r requirements.txt

# 3. Setup (interactive wizard)
python setup.py

# 4. Run
python main.py
```

The wizard will ask for:
- Your Hibachi **API Key** & **Secret Key** (from Settings → API Keys)
- Your **Account ID** (shown on the API Keys page)
- Grid/MM parameters (or use defaults)

## Strategies

### Grid Trading
Places buy/sell ladders around current price. Profits from sideways movement.

```
Price  ↑
105,000 |    SELL   SELL   SELL   SELL   SELL
102,500 |    
100,000 |━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  mid
 97,500 |    
 95,000 |    BUY    BUY    BUY    BUY    BUY
```

| Setting | Default | Description |
|---|---|---|
| `grid_count` | 10 | Levels per side (20 total) |
| `step_pct` | 0.15% | Distance between levels |
| `order_size_usdt` | $50 | USDT per order |
| `take_profit_pct` | 0.3% | Close at profit |
| `stop_loss_pct` | 2.0% | Close at loss |

### Market Making
Maintains bid/ask orders around mid-price. Adapts spread to volatility.

| Setting | Default | Description |
|---|---|---|
| `spread_pct` | 0.05% | Bid/Ask distance from mid |
| `order_size_usdt` | $100 | USDT per order |
| `max_orders_per_side` | 3 | Bid/ask levels |
| `max_long_usdt` | $500 | Long exposure cap |

## Commands

```bash
python setup.py                  # Interactive config
python main.py                   # Run all enabled strategies
python main.py --strategy grid   # Grid only
python main.py --strategy mm     # MM only
python main.py --dry-run         # Validate config, don't trade
```

## Safety

- `max_total_exposure` — global USDT limit
- `max_position_per_side` — per-direction cap
- `stop_loss_pct` — auto-close at loss threshold
- `cancel_on_price_move_pct` — pause MM on sharp moves

## License

MIT
