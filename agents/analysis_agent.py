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

How to format (this will be shown in a small popup window):
- Open with ONE plain sentence stating the bottom line — what happened and the most
  likely reason.
- Then a few short, scannable sections, each beginning with an emoji marker on its
  own line:
    📊  the price move — size, timeframe, notable volume or volatility
    📰  the news & catalysts that explain it — name sources and dates
    ⚠️  caveats, uncertainty, and the disclaimer
- Write in natural, flowing prose inside each section. Don't dump bullet lists.
- Do NOT use markdown tables (no "|" or "---"). Do NOT use markdown headers (no "#"
  or "##"). Do NOT use "**" bold. Plain text and the emoji markers only.
- Keep the whole thing concise — readable at a glance.

Grounding rules:
- Base every claim on what the tools returned. If the data is thin, say so plainly.
- Never invent news, earnings figures, or analyst actions the tools did not surface.
- End the ⚠️ section with exactly: This is an explanation of price moves, not investment advice.
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


class StockInsightAgent:
    """주가 변동 원인을 설명하는 에이전트."""

    def __init__(self, model: str | None = None, max_iterations: int = 6):
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 를 환경에서 읽음
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
        self.max_iterations = max_iterations

    def analyze(self, ticker: str, question: str | None = None) -> str:
        """티커의 최근 변동 원인을 분석해 텍스트로 반환한다."""
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
                messages=messages,
            )

            if response.stop_reason == "refusal":
                return "[분석 거부됨] 요청이 안전 정책에 의해 거부되었습니다."

            if response.stop_reason != "tool_use":
                return _extract_text(response)

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": self._run_tools(response)})

        return "[중단됨] 최대 반복 횟수에 도달했습니다."

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
