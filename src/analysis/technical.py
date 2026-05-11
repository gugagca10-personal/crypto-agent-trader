from dataclasses import dataclass
from typing import Optional

import pandas as pd
import pandas_ta as ta

from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TechnicalSignals:
    symbol: str
    current_price: float
    rsi: float
    macd: float
    macd_signal_val: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    ema_9: float
    ema_21: float
    volume_ratio: float
    signal_strength: int   # -100 to +100
    recommendation: str    # STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL

    def to_prompt_text(self) -> str:
        bb_pos = (
            "Near upper BB (overbought zone)"
            if self.current_price > self.bb_upper * 0.99
            else "Near lower BB (oversold zone)"
            if self.current_price < self.bb_lower * 1.01
            else "Within Bollinger Bands"
        )
        rsi_tag = (
            " [OVERSOLD]" if self.rsi < 30
            else " [OVERBOUGHT]" if self.rsi > 70
            else ""
        )
        hist_tag = " [BULLISH]" if self.macd_hist > 0 else " [BEARISH]"
        ema_trend = "BULLISH" if self.ema_9 > self.ema_21 else "BEARISH"
        vol_tag = " [HIGH VOLUME CONFIRMATION]" if self.volume_ratio > 1.5 else ""

        return (
            f"Symbol: {self.symbol} | Price: ${self.current_price:.8g}\n"
            f"RSI(14): {self.rsi:.1f}{rsi_tag}\n"
            f"MACD: {self.macd:.6g} | Signal: {self.macd_signal_val:.6g} | Hist: {self.macd_hist:.6g}{hist_tag}\n"
            f"BB Upper: {self.bb_upper:.6g} | Mid: {self.bb_mid:.6g} | Lower: {self.bb_lower:.6g} | {bb_pos}\n"
            f"EMA9: {self.ema_9:.6g} | EMA21: {self.ema_21:.6g} | Trend: {ema_trend}\n"
            f"Volume ratio vs 20-avg: {self.volume_ratio:.2f}x{vol_tag}\n"
            f"Signal Strength: {self.signal_strength:+d}/100 | Recommendation: {self.recommendation}\n"
        )


class TechnicalAnalyzer:
    def __init__(
        self,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: int = 2,
        ema_short: int = 9,
        ema_long: int = 21,
    ):
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.ema_short = ema_short
        self.ema_long = ema_long

    def analyze(self, df: pd.DataFrame, symbol: str) -> Optional[TechnicalSignals]:
        if len(df) < 50:
            logger.debug(f"Skipping {symbol}: only {len(df)} candles available (need 50)")
            return None

        try:
            close = df["close"]
            volume = df["volume"]

            rsi_series = ta.rsi(close, length=self.rsi_period)
            rsi_val = float(rsi_series.iloc[-1])

            macd_df = ta.macd(close, fast=self.macd_fast, slow=self.macd_slow, signal=self.macd_signal)
            macd_val = float(macd_df.iloc[-1, 0])
            macd_hist = float(macd_df.iloc[-1, 1])
            macd_sig_val = float(macd_df.iloc[-1, 2])
            prev_macd_hist = float(macd_df.iloc[-2, 1])

            bb = ta.bbands(close, length=self.bb_period, std=self.bb_std)
            bb_upper = float(bb.iloc[-1, 0])
            bb_mid = float(bb.iloc[-1, 1])
            bb_lower = float(bb.iloc[-1, 2])

            ema9 = float(ta.ema(close, length=self.ema_short).iloc[-1])
            ema21 = float(ta.ema(close, length=self.ema_long).iloc[-1])

            vol_ma = float(volume.rolling(20).mean().iloc[-1])
            vol_ratio = float(volume.iloc[-1]) / vol_ma if vol_ma > 0 else 1.0

            current_price = float(close.iloc[-1])

            # Score: -100 to +100
            score = 0

            if rsi_val < 30:
                score += 25
            elif rsi_val < 40:
                score += 10
            elif rsi_val > 70:
                score -= 25
            elif rsi_val > 60:
                score -= 10

            # MACD: fresh crossover is stronger signal
            if macd_hist > 0:
                score += 20 if prev_macd_hist <= 0 else 10
            else:
                score -= 20 if prev_macd_hist >= 0 else 10

            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pct = (current_price - bb_lower) / bb_range
                if bb_pct < 0.10:
                    score += 20
                elif bb_pct > 0.90:
                    score -= 20

            score += 15 if ema9 > ema21 else -15

            # Volume amplifies the existing signal direction
            if vol_ratio > 1.5 and score != 0:
                score = int(score * 1.2)

            score = max(-100, min(100, score))

            if score >= 50:
                recommendation = "STRONG_BUY"
            elif score >= 25:
                recommendation = "BUY"
            elif score <= -50:
                recommendation = "STRONG_SELL"
            elif score <= -25:
                recommendation = "SELL"
            else:
                recommendation = "HOLD"

            return TechnicalSignals(
                symbol=symbol,
                current_price=current_price,
                rsi=rsi_val,
                macd=macd_val,
                macd_signal_val=macd_sig_val,
                macd_hist=macd_hist,
                bb_upper=bb_upper,
                bb_mid=bb_mid,
                bb_lower=bb_lower,
                ema_9=ema9,
                ema_21=ema21,
                volume_ratio=vol_ratio,
                signal_strength=score,
                recommendation=recommendation,
            )

        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")
            return None
