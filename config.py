import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class TradingConfig:
    # Binance
    binance_api_key: str = field(default_factory=lambda: os.getenv("BINANCE_API_KEY", ""))
    binance_api_secret: str = field(default_factory=lambda: os.getenv("BINANCE_API_SECRET", ""))
    binance_testnet: bool = field(default_factory=lambda: os.getenv("BINANCE_TESTNET", "true").lower() == "true")

    # Anthropic
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"))

    # Cloudflare R2
    cf_account_id: str = field(default_factory=lambda: os.getenv("CLOUDFLARE_ACCOUNT_ID", ""))
    cf_r2_access_key: str = field(default_factory=lambda: os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID", ""))
    cf_r2_secret_key: str = field(default_factory=lambda: os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY", ""))
    cf_r2_bucket: str = field(default_factory=lambda: os.getenv("CLOUDFLARE_R2_BUCKET_NAME", "crypto-trader-logs"))

    # Trading parameters
    initial_balance_usdt: float = field(default_factory=lambda: float(os.getenv("INITIAL_USDT_BALANCE", "20")))
    max_trade_pct: float = field(default_factory=lambda: float(os.getenv("MAX_TRADE_PERCENTAGE", "0.30")))
    stop_loss_pct: float = field(default_factory=lambda: float(os.getenv("STOP_LOSS_PERCENTAGE", "0.04")))
    take_profit_pct: float = field(default_factory=lambda: float(os.getenv("TAKE_PROFIT_PERCENTAGE", "0.08")))
    min_confidence: int = field(default_factory=lambda: int(os.getenv("MIN_AI_CONFIDENCE", "70")))
    max_open_positions: int = field(default_factory=lambda: int(os.getenv("MAX_OPEN_POSITIONS", "2")))
    excluded_symbols: List[str] = field(
        default_factory=lambda: os.getenv("EXCLUDED_SYMBOLS", "BTC,GUN").upper().split(",")
    )
    top_pairs_count: int = field(default_factory=lambda: int(os.getenv("TOP_PAIRS_COUNT", "20")))

    # Operational
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "true").lower() == "true")
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    analysis_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("ANALYSIS_INTERVAL_MINUTES", "15"))
    )
    position_check_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POSITION_CHECK_INTERVAL_SECONDS", "60"))
    )

    # Technical analysis constants
    rsi_period: int = 14
    rsi_overbought: int = 70
    rsi_oversold: int = 30
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: int = 2
    ema_short: int = 9
    ema_long: int = 21


config = TradingConfig()
