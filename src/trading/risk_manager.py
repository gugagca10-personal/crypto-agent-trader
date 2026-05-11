from dataclasses import dataclass
from typing import Tuple

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

    def calculate_position_size(
        self, usdt_balance: float, confidence: int, open_count: int
    ) -> PositionSize:
        if open_count >= self.max_open_positions:
            return PositionSize(0, False, f"Max open positions ({self.max_open_positions}) reached")

        if usdt_balance < 1.0:
            return PositionSize(0, False, "USDT balance below $1 minimum")

        # Scale by confidence: 70%→70% of max, 100%→100% of max
        confidence_scale = max(0.5, confidence / 100)
        base = usdt_balance * self.max_trade_pct * confidence_scale

        # Keep 20% in reserve
        max_allowed = usdt_balance * 0.80
        amount = round(min(base, max_allowed), 2)
        amount = max(1.0, amount)

        return PositionSize(amount, True, f"${amount:.2f} at {confidence}% confidence")

    def calculate_stop_loss(self, entry: float, ai_stop: float = None) -> float:
        if ai_stop and ai_stop > 0:
            risk_pct = abs(entry - ai_stop) / entry
            if 0.01 <= risk_pct <= 0.10:
                return ai_stop
        return entry * (1 - self.stop_loss_pct)

    def calculate_take_profit(self, entry: float, ai_tp: float = None) -> float:
        if ai_tp and ai_tp > 0:
            reward_pct = abs(ai_tp - entry) / entry
            if 0.02 <= reward_pct <= 0.30:
                return ai_tp
        return entry * (1 + self.take_profit_pct)

    def should_close_position(
        self, entry: float, current: float, stop_loss: float, take_profit: float
    ) -> Tuple[bool, str]:
        if current <= stop_loss:
            pct = (current - entry) / entry * 100
            return True, f"Stop loss hit ({pct:.1f}%)"
        if current >= take_profit:
            pct = (current - entry) / entry * 100
            return True, f"Take profit hit (+{pct:.1f}%)"
        return False, "Within bounds"
