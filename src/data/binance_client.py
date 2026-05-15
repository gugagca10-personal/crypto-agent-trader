from typing import Dict, List, Optional

from binance import AsyncClient
from binance.exceptions import BinanceAPIException, BinanceRequestException

from ..utils.logger import get_logger
from ..utils.security import is_excluded_pair

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 10


class BinanceClientWrapper:
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True):
        if not api_key or not api_secret:
            raise ValueError("Binance API key and secret are required")
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client: Optional[AsyncClient] = None

    async def connect(self):
        self.client = await AsyncClient.create(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
            requests_params={"timeout": REQUEST_TIMEOUT_SECONDS},
        )
        mode = "Testnet" if self.testnet else "Mainnet"
        logger.info(f"Connected to Binance {mode}")

    async def close(self):
        if self.client:
            await self.client.close_connection()

    async def get_account_balance(self) -> Dict[str, float]:
        account = await self.client.get_account()
        return {
            b["asset"]: float(b["free"])
            for b in account["balances"]
            if float(b["free"]) > 0 or float(b["locked"]) > 0
        }

    async def get_usdt_balance(self) -> float:
        balances = await self.get_account_balance()
        return balances.get("USDT", 0.0)

    STABLECOIN_BASES = {
        "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "USDD",
        "PYUSD", "EURT", "EUR", "AEUR", "USDS"
    }

    async def get_top_usdt_pairs(self, count: int = 50, excluded: List[str] = None) -> List[Dict]:
        """Returns top USDT pairs as dicts with symbol + 24h change.
        Combines top by volume + top by 24h gainers to catch momentum plays.
        """
        excluded_bases = [s.upper() for s in (excluded or [])] + list(self.STABLECOIN_BASES)
        tickers = await self.client.get_ticker()

        usdt_pairs = []
        for t in tickers:
            sym = t["symbol"]
            if not sym.endswith("USDT"):
                continue
            if is_excluded_pair(sym, excluded_bases):
                continue
            try:
                quote_vol = float(t["quoteVolume"])
                change_pct = float(t.get("priceChangePercent", 0))
            except (ValueError, KeyError):
                continue
            # Need meaningful liquidity for day trade ($1M+ daily quote volume)
            if quote_vol < 1_000_000:
                continue
            usdt_pairs.append({
                "symbol": sym,
                "quote_volume": quote_vol,
                "change_24h_pct": change_pct,
            })

        # Top 70% by volume + top 30% by absolute 24h move (momentum candidates)
        vol_share = int(count * 0.7)
        mom_share = count - vol_share

        by_volume = sorted(usdt_pairs, key=lambda x: x["quote_volume"], reverse=True)[:vol_share]
        vol_symbols = {p["symbol"] for p in by_volume}

        by_momentum = sorted(
            (p for p in usdt_pairs if p["symbol"] not in vol_symbols),
            key=lambda x: abs(x["change_24h_pct"]),
            reverse=True,
        )[:mom_share]

        return by_volume + by_momentum

    async def get_klines(self, symbol: str, interval: str = "15m", limit: int = 100) -> List:
        return await self.client.get_klines(symbol=symbol, interval=interval, limit=limit)

    async def get_symbol_price(self, symbol: str) -> float:
        ticker = await self.client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    async def get_min_notional(self, symbol: str) -> float:
        info = await self.client.get_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s.get("filters", []):
                    if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                        return float(f.get("minNotional", 1.0))
        return 1.0

    async def place_market_buy(self, symbol: str, usdt_amount: float) -> Optional[Dict]:
        try:
            order = await self.client.order_market_buy(
                symbol=symbol,
                quoteOrderQty=round(usdt_amount, 2),
            )
            logger.info(f"BUY executed: {symbol} for ${usdt_amount:.2f}")
            return order
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Buy order failed for {symbol}: {e}")
            return None

    async def place_market_sell(self, symbol: str, quantity: float) -> Optional[Dict]:
        try:
            order = await self.client.order_market_sell(
                symbol=symbol,
                quantity=quantity,
            )
            logger.info(f"SELL executed: {symbol} qty={quantity}")
            return order
        except (BinanceAPIException, BinanceRequestException) as e:
            logger.error(f"Sell order failed for {symbol}: {e}")
            return None

    async def get_open_orders(self, symbol: str = None) -> List[Dict]:
        if symbol:
            return await self.client.get_open_orders(symbol=symbol)
        return await self.client.get_open_orders()
