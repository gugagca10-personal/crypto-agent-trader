import json
from dataclasses import dataclass
from typing import Dict, List, Optional

import anthropic

from .technical import TechnicalSignals
from ..utils.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are an expert cryptocurrency day trader and technical analyst operating on Binance Spot.
Your goal: identify the single best short-term (hours to 2 days) trade opportunity from the candidates provided.

Rules:
- Only recommend BUY when at least 3 indicators align strongly (RSI oversold, MACD bullish, price near lower BB, EMA uptrend, etc.)
- Always require minimum 2:1 risk/reward ratio
- Be conservative: only give confidence ≥ 70 for very clear setups
- If no setup is compelling, return action=HOLD with confidence=0
- You are trading USDT pairs on Binance Spot with approximately $20 total capital

Respond ONLY with valid JSON, no extra text:
{
  "action": "BUY" | "HOLD",
  "symbol": "XXXUSDT",
  "confidence": 0-100,
  "reasoning": "max 80 words",
  "suggested_entry": <float>,
  "stop_loss": <float>,
  "take_profit": <float>,
  "risk_reward_ratio": <float>
}"""


@dataclass
class TradeDecision:
    action: str
    symbol: str
    confidence: int
    reasoning: str
    suggested_entry: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float


class AIAnalyzer:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def analyze_opportunities(
        self,
        signals: List[TechnicalSignals],
        fear_greed: Dict,
        usdt_balance: float,
        open_positions: List[str],
    ) -> Optional[TradeDecision]:
        candidates = [
            s for s in signals
            if abs(s.signal_strength) >= 25 and s.symbol not in open_positions
        ]

        if not candidates:
            logger.info("No candidates with sufficient signal strength")
            return None

        candidates.sort(key=lambda x: abs(x.signal_strength), reverse=True)
        top = candidates[:5]

        signals_text = "\n---\n".join(s.to_prompt_text() for s in top)

        user_msg = (
            f"Top {len(top)} candidate pairs by signal strength:\n\n"
            f"{signals_text}\n"
            f"Market sentiment — Fear & Greed: {fear_greed['value']}/100 ({fear_greed['classification']})\n"
            f"Available USDT: ${usdt_balance:.2f}\n"
            f"Open positions: {open_positions or 'None'}\n\n"
            "Select the single best trade or HOLD if no setup is compelling."
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = response.content[0].text.strip()

            # Strip markdown code fences if present
            if "```" in raw:
                raw = raw.split("```")[1].lstrip("json").strip()

            data = json.loads(raw)

            decision = TradeDecision(
                action=data["action"].upper(),
                symbol=data["symbol"],
                confidence=int(data["confidence"]),
                reasoning=data["reasoning"],
                suggested_entry=float(data["suggested_entry"]),
                stop_loss=float(data["stop_loss"]),
                take_profit=float(data["take_profit"]),
                risk_reward_ratio=float(data["risk_reward_ratio"]),
            )

            logger.info(
                f"AI decision: {decision.action} {decision.symbol} "
                f"(confidence={decision.confidence}%, R/R={decision.risk_reward_ratio:.1f})"
            )
            return decision

        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            return None
