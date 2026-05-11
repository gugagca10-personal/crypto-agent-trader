import asyncio
import signal
from datetime import datetime

from config import config
from src.data.binance_client import BinanceClientWrapper
from src.data.market_data import MarketDataService
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.ai_analyzer import AIAnalyzer
from src.trading.risk_manager import RiskManager
from src.trading.executor import TradeExecutor
from src.storage.r2_client import R2Client
from src.utils.logger import get_logger

logger = get_logger("main")
_running = True


def _handle_shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received — finishing current cycle...")
    _running = False


async def run():
    global _running

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    logger.info("=" * 65)
    logger.info(f"  Crypto Trader Agent  |  {'DRY RUN' if config.dry_run else '*** LIVE TRADING ***'}")
    logger.info(f"  Budget: ~${config.initial_balance_usdt} USDT  |  Model: {config.claude_model}")
    logger.info(f"  Excluded: {config.excluded_symbols}  |  Max positions: {config.max_open_positions}")
    logger.info(f"  Analysis every {config.analysis_interval_minutes}min  |  Min confidence: {config.min_confidence}%")
    logger.info("=" * 65)

    binance = BinanceClientWrapper(
        config.binance_api_key,
        config.binance_api_secret,
        config.binance_testnet,
    )
    await binance.connect()

    market_data = MarketDataService(binance)
    technical = TechnicalAnalyzer(
        rsi_period=config.rsi_period,
        macd_fast=config.macd_fast,
        macd_slow=config.macd_slow,
        macd_signal=config.macd_signal,
        bb_period=config.bb_period,
        bb_std=config.bb_std,
        ema_short=config.ema_short,
        ema_long=config.ema_long,
    )
    ai = AIAnalyzer(config.anthropic_api_key, config.claude_model)
    risk = RiskManager(
        max_trade_pct=config.max_trade_pct,
        stop_loss_pct=config.stop_loss_pct,
        take_profit_pct=config.take_profit_pct,
        max_open_positions=config.max_open_positions,
    )
    executor = TradeExecutor(binance, risk, dry_run=config.dry_run)
    r2 = R2Client(
        config.cf_account_id,
        config.cf_r2_access_key,
        config.cf_r2_secret_key,
        config.cf_r2_bucket,
    )

    analysis_interval = config.analysis_interval_minutes * 60
    position_interval = config.position_check_interval_seconds

    last_analysis = 0.0
    last_position_check = 0.0

    logger.info("Agent running — press Ctrl+C to stop.")

    while _running:
        now = asyncio.get_event_loop().time()

        # ── 1. Check open positions for stop-loss / take-profit ──────────
        if now - last_position_check >= position_interval:
            if executor.open_positions:
                closed = await executor.check_and_close_positions()
                for trade in closed:
                    r2.log_trade({"type": "close", "timestamp": datetime.utcnow().isoformat(), **trade})
            last_position_check = now

        # ── 2. Full analysis cycle ────────────────────────────────────────
        if now - last_analysis >= analysis_interval:
            cycle_start = datetime.utcnow().strftime("%H:%M:%S UTC")
            logger.info(f"Analysis cycle started at {cycle_start}")

            try:
                usdt = await binance.get_usdt_balance()
                logger.info(f"USDT balance: ${usdt:.2f}")

                pairs = await binance.get_top_usdt_pairs(
                    count=config.top_pairs_count,
                    excluded=config.excluded_symbols,
                )
                logger.info(f"Scanning {len(pairs)} pairs — top 5: {pairs[:5]}")

                snapshots = await market_data.get_market_snapshot(pairs, interval="15m")
                fear_greed = await market_data.get_fear_greed_index()
                logger.info(
                    f"Fear & Greed: {fear_greed['value']}/100 ({fear_greed['classification']})"
                )

                signals = [
                    sig
                    for sym, df in snapshots.items()
                    if (sig := technical.analyze(df, sym)) is not None
                ]

                buys = sum(1 for s in signals if "BUY" in s.recommendation)
                sells = sum(1 for s in signals if "SELL" in s.recommendation)
                logger.info(
                    f"Technical signals: {buys} bullish, {sells} bearish, "
                    f"{len(signals)-buys-sells} neutral out of {len(signals)} pairs"
                )

                if executor.open_positions:
                    logger.info(f"Open positions:\n{executor.get_open_positions_summary()}")

                if signals and len(executor.open_positions) < config.max_open_positions:
                    decision = ai.analyze_opportunities(
                        signals=signals,
                        fear_greed=fear_greed,
                        usdt_balance=usdt,
                        open_positions=executor.get_open_symbols(),
                    )

                    if decision:
                        r2.log_decision({
                            "timestamp": datetime.utcnow().isoformat(),
                            "action": decision.action,
                            "symbol": decision.symbol,
                            "confidence": decision.confidence,
                            "reasoning": decision.reasoning,
                            "fear_greed": fear_greed["value"],
                        })

                        if decision.action == "BUY" and decision.confidence >= config.min_confidence:
                            logger.info(
                                f"AI → BUY {decision.symbol} ({decision.confidence}%): {decision.reasoning}"
                            )
                            pos = await executor.execute_buy(decision, usdt)
                            if pos:
                                r2.log_trade({
                                    "type": "open",
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "symbol": pos.symbol,
                                    "entry": pos.entry_price,
                                    "quantity": pos.quantity,
                                    "usdt_invested": pos.usdt_invested,
                                    "stop_loss": pos.stop_loss,
                                    "take_profit": pos.take_profit,
                                    "order_id": pos.order_id,
                                })
                        else:
                            logger.info(
                                f"AI → {decision.action} (confidence={decision.confidence}%) — no trade"
                            )

            except Exception as e:
                logger.error(f"Analysis cycle error: {e}", exc_info=True)

            last_analysis = now

        await asyncio.sleep(10)

    logger.info("Shutdown complete.")
    await binance.close()


if __name__ == "__main__":
    asyncio.run(run())
