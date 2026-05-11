from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..data.binance_client import BinanceClientWrapper
from ..analysis.ai_analyzer import TradeDecision
from ..utils.logger import get_logger
from ..utils.security import is_excluded_pair
from .risk_manager import RiskManager

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Position:
    symbol: str
    entry_price: float
    quantity: float
    usdt_invested: float
    stop_loss: float
    take_profit: float
    opened_at: datetime = field(default_factory=_utcnow)
    order_id: str = ""


class TradeExecutor:
    def __init__(
        self,
        binance: BinanceClientWrapper,
        risk: RiskManager,
        excluded_bases: List[str],
        dry_run: bool = True,
        consecutive_loss_limit: int = 3,
    ):
        self.binance = binance
        self.risk = risk
        self.excluded_bases = [b.upper() for b in excluded_bases]
        self.dry_run = dry_run
        self.consecutive_loss_limit = consecutive_loss_limit
        self.open_positions: Dict[str, Position] = {}
        self.consecutive_losses = 0
        self.circuit_open = False

        if dry_run:
            logger.warning("DRY RUN MODE active — no real orders will be placed")

    async def execute_buy(self, decision: TradeDecision, usdt_balance: float) -> Optional[Position]:
        if self.circuit_open:
            logger.warning(
                f"Circuit breaker open ({self.consecutive_losses} consecutive losses) — "
                "rejecting new trades until reset"
            )
            return None

        # Defense-in-depth: re-check exclusion at execution time even though
        # ai_analyzer already validates the symbol.
        if is_excluded_pair(decision.symbol, self.excluded_bases):
            logger.error(f"SECURITY: blocked buy on excluded pair {decision.symbol}")
            return None

        sizing = self.risk.calculate_position_size(
            usdt_balance, decision.confidence, len(self.open_positions)
        )
        if not sizing.is_valid:
            logger.info(f"Buy skipped — {sizing.reason}")
            return None

        stop_loss = self.risk.calculate_stop_loss(decision.suggested_entry, decision.stop_loss)
        take_profit = self.risk.calculate_take_profit(decision.suggested_entry, decision.take_profit)

        prefix = "[DRY RUN] " if self.dry_run else ""
        logger.info(
            f"{prefix}BUY {decision.symbol} ${sizing.usdt_amount:.2f} | "
            f"SL={stop_loss:.6g} TP={take_profit:.6g}"
        )

        if self.dry_run:
            entry_price = decision.suggested_entry
            quantity = sizing.usdt_amount / entry_price
            order_id = f"DRY_{decision.symbol}_{int(_utcnow().timestamp())}"
        else:
            order = await self.binance.place_market_buy(decision.symbol, sizing.usdt_amount)
            if not order:
                return None
            fills = order.get("fills") or []
            entry_price = (
                float(fills[0].get("price", decision.suggested_entry))
                if fills else decision.suggested_entry
            )
            executed = float(order.get("executedQty", 0))
            if executed <= 0:
                logger.error("Order returned with zero executed quantity — aborting position track")
                return None
            quantity = executed
            order_id = str(order["orderId"])

        pos = Position(
            symbol=decision.symbol,
            entry_price=entry_price,
            quantity=quantity,
            usdt_invested=sizing.usdt_amount,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order_id,
        )
        self.open_positions[decision.symbol] = pos
        logger.info(f"Position opened: {decision.symbol} {quantity:.6g} @ {entry_price:.6g}")
        return pos

    async def check_and_close_positions(self) -> List[Dict]:
        closed = []
        for symbol, pos in list(self.open_positions.items()):
            try:
                current_price = await self.binance.get_symbol_price(symbol)
                should_close, reason = self.risk.should_close_position(
                    pos.entry_price, current_price, pos.stop_loss, pos.take_profit
                )
                if not should_close:
                    continue

                pnl = (current_price - pos.entry_price) * pos.quantity
                pnl_pct = (current_price - pos.entry_price) / pos.entry_price * 100
                duration_min = int((_utcnow() - pos.opened_at).total_seconds() // 60)

                prefix = "[DRY RUN] " if self.dry_run else ""
                sign = "+" if pnl >= 0 else ""
                logger.info(
                    f"{prefix}CLOSE {symbol}: {reason} | "
                    f"PnL={sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%) | {duration_min}min held"
                )

                if not self.dry_run:
                    await self.binance.place_market_sell(symbol, pos.quantity)

                # Update circuit breaker state.
                if pnl < 0:
                    self.consecutive_losses += 1
                    if self.consecutive_losses >= self.consecutive_loss_limit:
                        self.circuit_open = True
                        logger.warning(
                            f"Circuit breaker tripped after {self.consecutive_losses} losses — "
                            "manual reset required"
                        )
                else:
                    self.consecutive_losses = 0

                del self.open_positions[symbol]
                closed.append({
                    "symbol": symbol,
                    "entry": pos.entry_price,
                    "exit": current_price,
                    "quantity": pos.quantity,
                    "usdt_invested": pos.usdt_invested,
                    "pnl_usdt": pnl,
                    "pnl_pct": pnl_pct,
                    "reason": reason,
                    "duration_min": duration_min,
                })

            except Exception as e:
                logger.error(f"Error checking position {symbol}: {e}")

        return closed

    def reset_circuit_breaker(self) -> None:
        self.consecutive_losses = 0
        self.circuit_open = False
        logger.info("Circuit breaker manually reset")

    def get_open_symbols(self) -> List[str]:
        return list(self.open_positions.keys())

    def get_open_positions_summary(self) -> str:
        if not self.open_positions:
            return "No open positions"
        lines = []
        for sym, pos in self.open_positions.items():
            lines.append(
                f"  {sym}: entry={pos.entry_price:.6g} SL={pos.stop_loss:.6g} TP={pos.take_profit:.6g}"
            )
        return "\n".join(lines)
