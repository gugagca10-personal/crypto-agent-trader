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
    ema_50: float
    volume_ratio: float
    atr: float                # Average True Range (14)
    atr_pct: float            # ATR as % of price (volatility measure)
    roc_5: float              # Rate of change over 5 candles (%)
    higher_tf_trend: str      # BULLISH | BEARISH | NEUTRAL (1h EMA21)
    change_24h_pct: float     # 24h price change %
    signal_strength: int      # -100 to +100
    recommendation: str       # STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL

    def to_prompt_text(self) -> str:
        bb_pos = (
            "Near upper BB (breakout zone)"
            if self.current_price > self.bb_upper * 0.99
            else "Near lower BB (support zone)"
            if self.current_price < self.bb_lower * 1.01
            else "Mid-band"
        )
        rsi_tag = (
            " [OVERSOLD]" if self.rsi < 30
            else " [OVERBOUGHT]" if self.rsi > 70
            else " [MOMENTUM]" if 50 <= self.rsi <= 65
            else ""
        )
        hist_tag = " [RISING]" if self.macd_hist > 0 else " [FALLING]"
        ema_trend = "BULLISH" if self.ema_9 > self.ema_21 > self.ema_50 else \
                    "BEARISH" if self.ema_9 < self.ema_21 < self.ema_50 else "MIXED"
        vol_tag = " [VOLUME SPIKE]" if self.volume_ratio > 2.0 else \
                  " [HIGH VOL]" if self.volume_ratio > 1.5 else ""
        roc_tag = " [STRONG]" if abs(self.roc_5) > 3 else ""

        return (
            f"Symbol: {self.symbol} | Price: ${self.current_price:.8g} | 24h: {self.change_24h_pct:+.2f}%\n"
            f"ATR(14): {self.atr:.6g} ({self.atr_pct:.2f}% of price) | ROC(5): {self.roc_5:+.2f}%{roc_tag}\n"
            f"RSI(14): {self.rsi:.1f}{rsi_tag}\n"
            f"MACD Hist: {self.macd_hist:.6g}{hist_tag} (signal line {self.macd_signal_val:.6g})\n"
            f"BB position: {bb_pos} (lower {self.bb_lower:.6g} / upper {self.bb_upper:.6g})\n"
            f"EMAs 9/21/50: {self.ema_9:.6g} / {self.ema_21:.6g} / {self.ema_50:.6g} → {ema_trend}\n"
            f"Higher TF (1h) trend: {self.higher_tf_trend}\n"
            f"Volume ratio: {self.volume_ratio:.2f}x{vol_tag}\n"
            f"Signal Strength: {self.signal_strength:+d}/100 | Local TA: {self.recommendation}\n"
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

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        higher_tf_df: Optional[pd.DataFrame] = None,
        change_24h_pct: float = 0.0,
    ) -> Optional[TechnicalSignals]:
        if len(df) < 50:
            logger.debug(f"Skipping {symbol}: only {len(df)} candles available (need 50)")
            return None

        try:
            high = df["high"]
            low = df["low"]
            close = df["close"]
            volume = df["volume"]

            rsi_val = float(ta.rsi(close, length=self.rsi_period).iloc[-1])

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
            ema50 = float(ta.ema(close, length=50).iloc[-1])

            vol_ma = float(volume.rolling(20).mean().iloc[-1])
            vol_ratio = float(volume.iloc[-1]) / vol_ma if vol_ma > 0 else 1.0

            current_price = float(close.iloc[-1])

            atr_val = float(ta.atr(high, low, close, length=14).iloc[-1])
            atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0.0

            # Rate of change over last 5 candles (~75min on 15m)
            roc_5 = float((current_price / float(close.iloc[-6]) - 1) * 100) if len(close) >= 6 else 0.0

            # Higher timeframe trend (1h EMA21 slope)
            higher_tf_trend = "NEUTRAL"
            if higher_tf_df is not None and len(higher_tf_df) >= 25:
                htf_close = higher_tf_df["close"]
                htf_ema21 = ta.ema(htf_close, length=21)
                if float(htf_ema21.iloc[-1]) > float(htf_ema21.iloc[-3]):
                    higher_tf_trend = "BULLISH"
                elif float(htf_ema21.iloc[-1]) < float(htf_ema21.iloc[-3]):
                    higher_tf_trend = "BEARISH"

            # Momentum-focused scoring for day trade of alts
            score = 0

            # RSI: momentum zone is more valuable than extremes
            if 50 <= rsi_val <= 65:
                score += 15  # rising momentum
            elif 45 <= rsi_val < 50:
                score += 5   # recovering
            elif rsi_val > 70:
                score -= 15
            elif rsi_val < 35:
                score -= 5   # weak — avoid catching falling knife

            # MACD: rising histogram (momentum building)
            if macd_hist > 0 and macd_hist > prev_macd_hist:
                score += 20
            elif macd_hist > 0:
                score += 10
            elif macd_hist < 0 and macd_hist < prev_macd_hist:
                score -= 20
            else:
                score -= 5

            # EMA alignment (9 > 21 > 50 = strong uptrend)
            if ema9 > ema21 > ema50:
                score += 25
            elif ema9 > ema21:
                score += 10
            elif ema9 < ema21 < ema50:
                score -= 25
            elif ema9 < ema21:
                score -= 10

            # BB: prefer mid-band breakouts over reversion plays
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pct = (current_price - bb_lower) / bb_range
                if 0.55 <= bb_pct <= 0.85:  # breakout zone
                    score += 10
                elif bb_pct > 0.95:  # overextended
                    score -= 10

            # Higher TF alignment
            if higher_tf_trend == "BULLISH":
                score += 15
            elif higher_tf_trend == "BEARISH":
                score -= 15

            # ROC momentum confirmation
            if roc_5 > 2:
                score += 10
            elif roc_5 < -3:
                score -= 10

            # Volume amplifies — strict thresholds
            if vol_ratio > 2.0 and score > 0:
                score = int(score * 1.3)
            elif vol_ratio > 1.5 and score > 0:
                score = int(score * 1.15)
            elif vol_ratio < 0.5:
                score = int(score * 0.7)  # low conviction without volume

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
                ema_50=ema50,
                volume_ratio=vol_ratio,
                atr=atr_val,
                atr_pct=atr_pct,
                roc_5=roc_5,
                higher_tf_trend=higher_tf_trend,
                change_24h_pct=change_24h_pct,
                signal_strength=score,
                recommendation=recommendation,
            )

        except Exception as e:
            logger.error(f"Technical analysis failed for {symbol}: {e}")
            return None
