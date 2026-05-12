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

    async def get_top_usdt_pairs(self, count: int = 20, excluded: List[str] = None) -> List[str]:
        excluded_bases = [s.upper() for s in (excluded or [])]
        tickers = await self.client.get_ticker()
        usdt_pairs = [
            t for t in tickers
            if t["symbol"].endswith("USDT")
            and not is_excluded_pair(t["symbol"], excluded_bases)
        ]
        usdt_pairs.sort(key=lambda x: float(x["quoteVolume"]), reverse=True)
        return [t["symbol"] for t in usdt_pairs[:count]]

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
