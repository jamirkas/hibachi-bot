"""
Web dashboard for real-time bot monitoring.

Usage:
    python dashboard.py           # Standalone
    python main.py                # With display.web_dashboard: true
"""

import asyncio
import json
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

logger = logging.getLogger("hibachi.dashboard")


@dataclass
class BotState:
    """Shared state between trading engine and dashboard."""

    running: bool = False

    # Account
    balance: float = 0.0
    account_id: int = 0

    # Performance
    total_pnl: float = 0.0
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    pnl_history: list[dict] = field(default_factory=list)

    # Current state
    positions: list[dict] = field(default_factory=list)
    active_orders: list[dict] = field(default_factory=list)
    recent_events: list[dict] = field(default_factory=list)   # Last 50 events
    grid_levels: list[dict] = field(default_factory=list)

    # Strategies
    strategies: list[str] = field(default_factory=list)
    symbol: str = "BTC/USDT-P"
    mark_price: float = 0.0
    started_at: float = 0.0

    def add_event(self, event_type: str, detail: str, pnl: float = 0.0):
        self.recent_events.append({
            "time": time.strftime("%H:%M:%S"),
            "type": event_type,
            "detail": detail,
            "pnl": pnl,
        })
        if len(self.recent_events) > 50:
            self.recent_events = self.recent_events[-50:]

    def record_pnl(self, amount: float):
        self.total_pnl += amount
        self.total_trades += 1
        if amount > 0:
            self.win_trades += 1
        else:
            self.loss_trades += 1
        self.pnl_history.append({
            "time": time.strftime("%H:%M:%S"),
            "pnl": round(self.total_pnl, 2),
        })
        if len(self.pnl_history) > 200:
            self.pnl_history = self.pnl_history[-200:]

    def to_dict(self) -> dict:
        uptime = int(time.time() - self.started_at) if self.started_at else 0
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        return {
            "running": self.running,
            "uptime": f"{h:02d}:{m:02d}:{s:02d}",
            "balance": round(self.balance, 2),
            "account_id": self.account_id,
            "total_pnl": round(self.total_pnl, 2),
            "total_trades": self.total_trades,
            "win_trades": self.win_trades,
            "loss_trades": self.loss_trades,
            "win_rate": round(self.win_trades / max(self.total_trades, 1) * 100, 1),
            "positions": self.positions,
            "active_orders": self.active_orders,
            "recent_events": self.recent_events[-20:],
            "grid_levels": self.grid_levels,
            "strategies": self.strategies,
            "symbol": self.symbol,
            "mark_price": self.mark_price,
            "pnl_history": self.pnl_history,
        }


# ── FastAPI App ──────────────────────────────────────

TEMPLATE_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Hibachi Bot Dashboard", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Global state reference (set by create_dashboard)
_state: Optional[BotState] = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/state")
async def api_state():
    if _state is None:
        return JSONResponse({"error": "Bot not started"}, status_code=503)
    return JSONResponse(_state.to_dict())


def create_dashboard(state: BotState, port: int = 8080):
    """Start dashboard server in background thread."""
    global _state
    _state = state

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def run():
        asyncio.run(server.serve())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info(f"📊 Dashboard: http://localhost:{port}")
    return thread
