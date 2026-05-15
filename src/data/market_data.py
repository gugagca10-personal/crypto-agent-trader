import asyncio
from typing import Dict, List
from urllib.parse import urlparse

import aiohttp
import pandas as pd

from .binance_client import BinanceClientWrapper
from ..utils.logger import get_logger

logger = get_logger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
ALLOWED_FEAR_GREED_HOST = "api.alternative.me"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=5)


class MarketDataService:
    def __init__(self, binance: BinanceClientWrapper):
        self.binance = binance

    async def get_ohlcv(self, symbol: str, interval: str = "15m", limit: int = 100) -> pd.DataFrame:
        klines = await self.binance.get_klines(symbol, interval, limit)
        df = pd.DataFrame(klines, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        df = df[["timestamp", "open", "high", "low", "close", "volume", "quote_volume"]].copy()
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    async def get_fear_greed_index(self) -> Dict:
        # Defense-in-depth: verify the URL hasn't been tampered with at runtime.
        host = urlparse(FEAR_GREED_URL).hostname
        if host != ALLOWED_FEAR_GREED_HOST:
            logger.error(f"Fear & Greed URL host mismatch: {host} — refusing request")
            return {"value": 50, "classification": "Neutral", "timestamp": "blocked"}

        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                async with session.get(FEAR_GREED_URL) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                    entry = data["data"][0]
                    return {
                        "value": int(entry["value"]),
                        "classification": entry["value_classification"],
                        "timestamp": entry["timestamp"],
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError) as e:
            logger.warning(f"Fear & Greed API unreachable: {e}")
            return {"value": 50, "classification": "Neutral", "timestamp": "unknown"}

    async def get_market_snapshot(
        self, symbols: List[str], interval: str = "15m"
    ) -> Dict[str, pd.DataFrame]:
        results: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            try:
                results[sym] = await self.get_ohlcv(sym, interval)
                await asyncio.sleep(0.05)  # avoid hitting rate limits
            except Exception as e:
                logger.error(f"Failed to fetch {sym}: {e}")
        return results

    async def get_multi_tf_snapshot(
        self, symbols: List[str]
    ) -> Dict[str, Dict[str, pd.DataFrame]]:
        """Fetches 15m and 1h candles for each symbol. Returns {symbol: {tf: df}}."""
        results: Dict[str, Dict[str, pd.DataFrame]] = {}
        for sym in symbols:
            try:
                df_15m = await self.get_ohlcv(sym, "15m", limit=100)
                await asyncio.sleep(0.05)
                df_1h = await self.get_ohlcv(sym, "1h", limit=50)
                await asyncio.sleep(0.05)
                results[sym] = {"15m": df_15m, "1h": df_1h}
            except Exception as e:
                logger.error(f"Failed to fetch multi-TF {sym}: {e}")
        return results
