from dataclasses import dataclass
from typing import Optional, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PositionSize:
    usdt_amount: float
    is_valid: bool
    reason: str


class RiskManager:
    def __init__(
        self,
        max_trade_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        max_open_positions: int,
    ):
        self.max_trade_pct = max_trade_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_open_positions = max_open_positions

    MIN_ORDER_USDT = 6.0  # Binance minimum notional is $5; use $6 as safe floor

    def calculate_position_size(
        self, usdt_balance: float, confidence: int, open_count: int
    ) -> PositionSize:
        if usdt_balance < self.MIN_ORDER_USDT:
            return PositionSize(0, False, f"USDT balance below ${self.MIN_ORDER_USDT} minimum")

        available = usdt_balance * 0.80  # keep 20% liquid

        # How many slots fit without going below minimum order size
        slots = min(self.max_open_positions, max(1, int(available / self.MIN_ORDER_USDT)))

        if open_count >= slots:
            return PositionSize(0, False, f"Max positions for current balance ({slots}) reached")

        amount = round(available / slots, 2)
        return PositionSize(amount, True, f"${amount:.2f} (slot {open_count+1}/{slots})")

    def calculate_stop_loss(self, entry: float, ai_stop: float = None, atr: float = 0.0) -> float:
        # Prefer ATR-based stop (1.8x ATR below entry) for volatility-adjusted risk
        if atr > 0:
            atr_stop = entry - (atr * 1.8)
            atr_risk_pct = (entry - atr_stop) / entry
            if 0.01 <= atr_risk_pct <= 0.12:
                return atr_stop

        if ai_stop and ai_stop > 0:
            risk_pct = abs(entry - ai_stop) / entry
            if 0.01 <= risk_pct <= 0.12:
                return ai_stop

        return entry * (1 - self.stop_loss_pct)

    def calculate_take_profit(self, entry: float, ai_tp: float = None, atr: float = 0.0) -> float:
        # ATR-based TP at 3.5x ATR (gives ~2:1 R/R with 1.8x ATR stop)
        if atr > 0:
            atr_tp = entry + (atr * 3.5)
            reward_pct = (atr_tp - entry) / entry
            if 0.02 <= reward_pct <= 0.40:
                return atr_tp

        if ai_tp and ai_tp > 0:
            reward_pct = abs(ai_tp - entry) / entry
            if 0.02 <= reward_pct <= 0.40:
                return ai_tp

        return entry * (1 + self.take_profit_pct)

    def update_trailing_stop(
        self, entry: float, current: float, current_stop: float, atr: float = 0.0
    ) -> Optional[float]:
        """If position is in profit, ratchet stop loss upward to lock gains.
        Returns new stop only if it's higher than current; None otherwise.
        """
        profit_pct = (current - entry) / entry

        # Stage 1: position is +2%+ → move stop to breakeven + 0.3%
        if profit_pct >= 0.02:
            new_stop = entry * 1.003
            # Stage 2: position is +5%+ → trail by 1.5x ATR below current
            if profit_pct >= 0.05 and atr > 0:
                trail = current - (atr * 1.5)
                new_stop = max(new_stop, trail)
            # Stage 3: position is +10%+ → trail by 1x ATR below current
            elif profit_pct >= 0.10 and atr > 0:
                trail = current - (atr * 1.0)
                new_stop = max(new_stop, trail)

            if new_stop > current_stop:
                return new_stop
        return None

    def should_close_position(
        self, entry: float, current: float, stop_loss: float, take_profit: float
    ) -> Tuple[bool, str]:
        if current <= stop_loss:
            pct = (current - entry) / entry * 100
            sign = "+" if pct >= 0 else ""
            return True, f"Stop hit ({sign}{pct:.1f}%)"
        if current >= take_profit:
            pct = (current - entry) / entry * 100
            return True, f"Take profit hit (+{pct:.1f}%)"
        return False, "Within bounds"
