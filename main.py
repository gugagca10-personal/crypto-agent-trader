import asyncio
import signal
from datetime import datetime, timezone

from config import config
from src.data.binance_client import BinanceClientWrapper
from src.data.market_data import MarketDataService
from src.analysis.technical import TechnicalAnalyzer
from src.analysis.ai_analyzer import AIAnalyzer
from src.trading.risk_manager import RiskManager
from src.trading.executor import TradeExecutor
from src.storage.r2_client import R2Client
from src.utils.logger import get_logger
from src.utils.security import (
    assert_env_file_secure,
    assert_balance_in_expected_range,
    redact_key,
)

logger = get_logger("main")
_running = True


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _handle_shutdown(signum, frame):
    global _running
    logger.info("Shutdown signal received — finishing current cycle...")
    _running = False


def _preflight_checks() -> None:
    """Fail fast on misconfigurations before any network or trading call."""
    assert_env_file_secure(".env")

    if not config.binance_api_key or not config.binance_api_secret:
        raise RuntimeError("Binance API credentials missing from .env")
    if not config.anthropic_api_key:
        raise RuntimeError("Anthropic API key missing from .env")
    if not (0.01 <= config.max_trade_pct <= 0.50):
        raise RuntimeError(
            f"MAX_TRADE_PERCENTAGE={config.max_trade_pct} unsafe — must be between 0.01 and 0.50"
        )
    if not (0.005 <= config.stop_loss_pct <= 0.20):
        raise RuntimeError(
            f"STOP_LOSS_PERCENTAGE={config.stop_loss_pct} unsafe — must be between 0.005 and 0.20"
        )
    if not config.excluded_symbols or all(not s.strip() for s in config.excluded_symbols):
        raise RuntimeError("EXCLUDED_SYMBOLS is empty — BTC and GUN must be excluded")
    if config.min_confidence < 50:
        logger.warning(
            f"MIN_AI_CONFIDENCE={config.min_confidence} is below 50 — high risk of bad trades"
        )

    logger.info(
        f"Preflight OK | Binance key: {redact_key(config.binance_api_key)} | "
        f"Anthropic key: {redact_key(config.anthropic_api_key)}"
    )


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

    _preflight_checks()

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
    executor = TradeExecutor(
        binance,
        risk,
        excluded_bases=config.excluded_symbols,
        dry_run=config.dry_run,
    )
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

    try:
        while _running:
            now = asyncio.get_event_loop().time()

            if now - last_position_check >= position_interval:
                if executor.open_positions:
                    closed = await executor.check_and_close_positions()
                    for trade in closed:
                        r2.log_trade({"type": "close", "timestamp": _utcnow_iso(), **trade})
                last_position_check = now

            if now - last_analysis >= analysis_interval:
                logger.info(f"Analysis cycle started at {_utcnow_iso()}")

                try:
                    usdt = await binance.get_usdt_balance()
                    assert_balance_in_expected_range(usdt, config.initial_balance_usdt)
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
                        decision = await asyncio.to_thread(
                            ai.analyze_opportunities,
                            signals,
                            fear_greed,
                            usdt,
                            executor.get_open_symbols(),
                            config.excluded_symbols,
                        )

                        if decision:
                            r2.log_decision({
                                "timestamp": _utcnow_iso(),
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
                                        "timestamp": _utcnow_iso(),
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

                except RuntimeError as e:
                    # Preflight or runtime safety failure — fatal.
                    logger.critical(f"Safety check failed: {e}")
                    _running = False
                except Exception as e:
                    logger.error(f"Analysis cycle error: {e}", exc_info=True)

                last_analysis = now

            await asyncio.sleep(10)
    finally:
        logger.info("Closing Binance connection...")
        await binance.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(run())
