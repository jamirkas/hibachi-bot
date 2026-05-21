"""
Risk management utilities.
"""

from dataclasses import dataclass


@dataclass
class RiskConfig:
    max_position_size: float          # USDT
    max_total_exposure: float          # USDT
    stop_loss_pct: float               # e.g. 0.05 = 5%
    max_grid_levels: int               # max grid orders
    min_order_size: float              # minimum USDT per order
    max_open_orders: int               # rate-limit guard


def position_size(balance: float, price: float, risk_per_trade: float) -> float:
    """
    Calculate position size based on risk %.
    
    Args:
        balance: available USDT balance
        price: current asset price
        risk_per_trade: fraction of balance to risk (0.0-1.0)
    
    Returns:
        Quantity in base asset
    """
    usdt_risk = balance * risk_per_trade
    return usdt_risk / price


def within_limits(order_value: float, balance: float, cfg: RiskConfig) -> bool:
    """Check if order value respects risk limits."""
    if order_value < cfg.min_order_size:
        return False
    if order_value > cfg.max_position_size:
        return False
    if order_value > balance * 0.95:  # Leave 5% buffer
        return False
    return True
