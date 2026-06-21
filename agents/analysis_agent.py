"""주가 변동 원인을 분석하는 Claude 에이전트.

설계:
- `claude-opus-4-8` + adaptive thinking 으로 추론.
- tools/ 의 함수들을 tool use 로 호출해 시세·뉴스 데이터를 수집한다.
- 수집한 근거를 종합해 "왜 움직였는가"를 설명한다.

수동 agentic loop 을 사용해 각 tool 호출을 명시적으로 제어한다.
"""

from __future__ import annotations

import json
import os

import anthropic

from tools import get_price_history, get_recent_move, get_recent_news

SYSTEM_PROMPT = """\
You are a sharp markets analyst who explains *why* a stock moved — the way a
knowledgeable friend would: clear, direct, and easy to read at a glance.

Always respond in English.

How to work:
- Use the tools to pull the recent price move and the relevant news.
- Connect specific events to the price action with concrete dates and numbers.
- Separate company-specific drivers from sector/macro moves when the evidence supports it.

Return your final answer as the structured object the schema defines. Field guidance:
- headline: ONE short, punchy line naming the main reason the stock moved
  (e.g. "Pulled down by self-driving regulation concerns"). No ticker, no % sign.
- ticker: the symbol analyzed, uppercase.
- pct_change: percent change over the lookback window, as a number (negative if down).
- direction: "up", "down", or "flat" — must match the sign of pct_change.
- sources_count: how many distinct news items you actually used.
- price_window: the price-data date range, e.g. "6/12–6/18".
- bullets: 2-4 short one-sentence bullets explaining the move. Tag each as "price"
  (what the price did) or "news" (the catalyst / why). Include at least one "price"
  and one "news" bullet when the data allows.
- tags: 2-3 short theme labels, 1-3 words each (e.g. "AI infrastructure",
  "Q4 earnings", "valuation concerns").
- full_analysis: a longer human-readable write-up for the terminal. Plain text with
  emoji section markers (📊 Price Move, 📰 News & Catalysts, ⚠️ Caveats), short "- "
  bullets, no markdown tables / headers / "**" bold. End the ⚠️ section with exactly:
  - This is an explanation of price moves, not investment advice.

Grounding rules:
- Base every field on what the tools returned. If the data is thin, say so in the
  bullets and full_analysis, and keep sources_count honest.
- Never invent news, earnings figures, or analyst actions the tools did not surface.
"""

# 에이전트가 호출할 수 있는 tool 스키마 (Anthropic Messages API 형식).
TOOLS = [
    {
        "name": "get_recent_move",
        "description": "최근 N 거래일간의 가격 변동률, 최대 낙폭, 평균 거래량을 요약한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "종목 코드 (예: AAPL)"},
                "lookback_days": {"type": "integer", "description": "변동 계산 거래일 수", "default": 5},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_price_history",
        "description": "티커의 과거 OHLCV 시세를 조회한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "period": {"type": "string", "description": "1d/5d/1mo/3mo/6mo/1y/ytd/max", "default": "1mo"},
                "interval": {"type": "string", "description": "1d/1h/5m 등", "default": "1d"},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_recent_news",
        "description": "종목/키워드 관련 최신 뉴스 헤드라인을 조회한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "회사명 또는 티커"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
]

# tool 이름 -> 실제 구현 매핑.
_DISPATCH = {
    "get_recent_move": get_recent_move,
    "get_price_history": get_price_history,
    "get_recent_news": get_recent_news,
}

# 최종 답변을 강제할 구조화 출력 스키마 (popup 카드가 사용할 데이터).
ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "ticker": {"type": "string"},
        "pct_change": {"type": "number"},
        "direction": {"type": "string", "enum": ["up", "down", "flat"]},
        "sources_count": {"type": "integer"},
        "price_window": {"type": "string"},
        "bullets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": ["price", "news"]},
                    "text": {"type": "string"},
                },
                "required": ["type", "text"],
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "full_analysis": {"type": "string"},
    },
    "required": [
        "headline",
        "ticker",
        "pct_change",
        "direction",
        "sources_count",
        "price_window",
        "bullets",
        "tags",
        "full_analysis",
    ],
}


class StockInsightAgent:
    """주가 변동 원인을 설명하는 에이전트."""

    def __init__(self, model: str | None = None, max_iterations: int = 6):
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 를 환경에서 읽음
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
        self.max_iterations = max_iterations

    def analyze(self, ticker: str, question: str | None = None) -> str:
        """티커 분석 결과를 사람이 읽기 좋은 텍스트(full_analysis)로 반환한다."""
        return self.analyze_structured(ticker, question)["full_analysis"]

    def analyze_structured(self, ticker: str, question: str | None = None) -> dict:
        """티커의 최근 변동 원인을 분석해 구조화된 dict 로 반환한다.

        구조화 출력(JSON 스키마)으로 최종 답변을 강제하며,
        파싱 실패/거부/중단 시에는 안전한 fallback dict 를 돌려준다.
        반환 키: headline, ticker, pct_change, direction, sources_count,
                price_window, bullets[{type,text}], tags[], full_analysis
        """
        prompt = (
            f"종목 {ticker} 의 최근 주가 변동 원인을 분석해줘."
            if not question
            else f"종목 {ticker} 에 대해: {question}"
        )
        messages: list[dict] = [{"role": "user", "content": prompt}]

        for _ in range(self.max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                output_config={
                    "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}
                },
                messages=messages,
            )

            if response.stop_reason == "refusal":
                return _fallback(ticker, "[분석 거부됨] 요청이 안전 정책에 의해 거부되었습니다.")

            if response.stop_reason != "tool_use":
                return _parse(ticker, _extract_text(response))

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": self._run_tools(response)})

        return _fallback(ticker, "[중단됨] 최대 반복 횟수에 도달했습니다.")

    @staticmethod
    def _run_tools(response) -> list[dict]:
        """응답 내 tool_use 블록을 실행하고 tool_result 블록 리스트를 만든다."""
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = _DISPATCH[block.name](**block.input)
                content, is_error = json.dumps(output, ensure_ascii=False), False
            except Exception as exc:  # noqa: BLE001 - tool 오류를 모델에 전달
                content, is_error = f"tool error: {exc}", True
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
        return results


def _extract_text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _parse(ticker: str, text: str) -> dict:
    """모델의 JSON 최종 답변을 dict 로 파싱한다. 실패 시 fallback."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError, TypeError):
        return _fallback(ticker, text)
    data.setdefault("ticker", ticker)
    data.setdefault("full_analysis", text)
    return data


def _fallback(ticker: str, text: str) -> dict:
    """파싱 실패/거부/중단 시 안전한 기본 구조."""
    return {
        "headline": "Analysis",
        "ticker": ticker,
        "pct_change": 0.0,
        "direction": "flat",
        "sources_count": 0,
        "price_window": "",
        "bullets": [],
        "tags": [],
        "full_analysis": text or "No analysis available.",
    }
