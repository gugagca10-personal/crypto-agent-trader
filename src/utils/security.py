"""Security utilities — validations and safety checks for the trading agent."""
import os
import re
import stat
from pathlib import Path
from typing import List

from .logger import get_logger

logger = get_logger(__name__)

VALID_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}USDT$")
VALID_ACCOUNT_ID_RE = re.compile(r"^[a-f0-9]{32}$")
SAFE_HOSTS = {
    "api.binance.com",
    "testnet.binance.vision",
    "api.binance.us",
    "api.alternative.me",
    "api.anthropic.com",
}


def assert_env_file_secure(path: str = ".env") -> None:
    """Refuse to start if .env exists with permissions wider than 600."""
    p = Path(path)
    if not p.exists():
        return
    mode = p.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError(
            f"{path} permissions are too open ({oct(mode & 0o777)}). "
            f"Run: chmod 600 {path}"
        )


def is_safe_symbol(symbol: str, excluded_bases: List[str], candidates: List[str]) -> bool:
    """Symbol must: end in USDT, match valid format, not be in excluded list,
    AND be in the candidate list that the AI was given."""
    if not symbol or not isinstance(symbol, str):
        return False
    symbol = symbol.upper()
    if not VALID_SYMBOL_RE.match(symbol):
        return False
    if symbol not in candidates:
        return False
    base = symbol[:-4]  # strip USDT suffix to get base asset
    for ex in excluded_bases:
        if base == ex.upper():
            return False
    return True


def is_excluded_pair(symbol: str, excluded_bases: List[str]) -> bool:
    """Return True if the symbol's base asset matches an excluded asset exactly.
    Avoids false positives from naive startswith (e.g. BTCB ≠ BTC)."""
    if not symbol.endswith("USDT"):
        return True
    base = symbol[:-4]
    excluded_upper = [e.upper() for e in excluded_bases]
    return base in excluded_upper


def validate_account_id(account_id: str) -> bool:
    """Cloudflare account IDs are 32-char lowercase hex strings."""
    return bool(account_id) and bool(VALID_ACCOUNT_ID_RE.match(account_id))


def assert_balance_in_expected_range(balance: float, configured: float, factor: float = 3.0) -> None:
    """Abort if live balance is unexpectedly large vs configured budget — protects
    against accidentally trading the user's main capital."""
    if balance > configured * factor:
        raise RuntimeError(
            f"USDT balance ${balance:.2f} exceeds {factor}x configured budget "
            f"${configured:.2f}. Refusing to trade — verify INITIAL_USDT_BALANCE or move excess funds."
        )


def redact_key(value: str) -> str:
    """Show only first 4 and last 4 chars of a secret for safe logging."""
    if not value or len(value) < 12:
        return "***"
    return f"{value[:4]}...{value[-4:]}"
