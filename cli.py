#!/usr/bin/env python3
"""주가 변동 원인 분석 CLI.

크롬 등에서 선택한 티커를 단축키로 넘겨 빠르게 분석하기 위한 진입점.

사용법:
    python cli.py TSLA
    echo "TSLA" | python cli.py
    python cli.py TSLA --notify      # macOS 알림으로도 표시

기존 agents/analysis_agent.py 를 그대로 재사용한다.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# 팝업에 우선적으로 보여줄 섹션 마커(이모지). 분석 출력의 섹션 헤더와 맞춘다:
#   📊 가격 변동 / 📰 뉴스·촉매 / ⚠️ 주의사항·면책
POPUP_SECTION_KEYWORDS = ("📊", "📰", "⚠️")

from dotenv import load_dotenv


def read_ticker(arg: str | None) -> str:
    """인자 또는 stdin 에서 티커를 추출한다 (공백/줄바꿈 제거, 대문자)."""
    raw = arg if arg is not None else sys.stdin.read()
    token = raw.strip().split()[0] if raw.strip() else ""
    return token.upper()


def summary_line(text: str, limit: int = 120) -> str:
    """분석 결과에서 알림에 쓸 핵심 한 줄 요약을 뽑는다 (첫 비어있지 않은 줄)."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s if len(s) <= limit else s[: limit - 1] + "…"
    return "분석 완료"


def _split_emoji_sections(text: str) -> list[dict]:
    """분석 텍스트를 이모지 마커(📊/📰/⚠️) 기준 섹션으로 나눈다.

    각 섹션: {"header": "📊 Price Move", "bullets": ["- ...", "- ..."]}
    첫 마커 이전의 리드 문장 등은 무시한다 (팝업에는 섹션만 표시).
    """
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped.startswith(m) for m in POPUP_SECTION_KEYWORDS):
            cur = {"header": stripped, "bullets": []}
            sections.append(cur)
        elif cur is not None and stripped:
            cur["bullets"].append(stripped)
    return sections


def _render_section(s: dict) -> str:
    return s["header"] + ("\n" + "\n".join(s["bullets"]) if s["bullets"] else "")


def popup_excerpt(text: str, limit: int = 600) -> str:
    """팝업용 짧은 발췌를 만든다.

    세 섹션(📊/📰/⚠️)을 모두 포함하되 전체를 limit(기본 600자) 이내로 유지한다.
    너무 길면 ⚠️ Caveats 섹션은 건드리지 않고, 나머지 섹션의 뒤쪽 bullet 부터
    잘라낸다 — Caveats 가 잘려나가는 일이 없도록 보장한다.
    """
    text = text.strip()
    sections = _split_emoji_sections(text)
    if not sections:
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    caveat = next((s for s in sections if s["header"].startswith("⚠️")), None)
    others = [s for s in sections if s is not caveat]

    sep = "\n\n"
    # Caveats 가 들어갈 자리를 먼저 확보하고, 남는 예산으로 나머지 섹션을 채운다.
    reserve = len(_render_section(caveat)) + len(sep) if caveat else 0
    budget = max(0, limit - reserve)

    pieces: list[str] = []
    for s in others:
        # 예산을 초과하면 이 섹션의 뒤쪽 bullet 부터 제거 (헤더는 유지).
        while s["bullets"] and len(sep.join(pieces + [_render_section(s)])) > budget:
            s["bullets"].pop()
        pieces.append(_render_section(s))

    if caveat is not None:
        pieces.append(_render_section(caveat))  # 항상 통째로, 마지막에

    return sep.join(pieces)


def popup_macos(title: str, message: str) -> None:
    """macOS display dialog 팝업으로 분석 발췌를 표시한다 (확인 버튼 하나).

    notify_macos 와 동일하게 텍스트/제목/버튼 라벨을 모두 argv 로 넘겨
    한글·따옴표·줄바꿈이 있어도 osascript 파싱 에러(-2741)가 나지 않게 한다.
    """
    if sys.platform != "darwin":
        return
    body = popup_excerpt(message)
    script = (
        "on run argv\n"
        "    display dialog (item 1 of argv) with title (item 2 of argv) "
        "buttons {(item 3 of argv)} default button (item 3 of argv)\n"
        "end run"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, body, title, "확인"],
            check=False,
            timeout=300,
        )
    except Exception:  # noqa: BLE001 - 팝업 실패가 본 분석을 막지 않도록
        pass


def notify_macos(title: str, message: str) -> None:
    """macOS 알림 센터에 한 줄 요약 알림을 띄운다. macOS 가 아니면 조용히 무시.

    문자열을 AppleScript 소스에 직접 끼워넣지 않고 argv 로 전달한다.
    이렇게 하면 따옴표·한글·특수문자 이스케이프 문제가 원천적으로 사라진다.
    (직접 끼워넣으면 한글이 \\uXXXX 로 바뀌어 osascript 가 파싱에 실패함.)
    """
    if sys.platform != "darwin":
        return
    body = summary_line(message)
    script = (
        "on run argv\n"
        "    display notification (item 1 of argv) with title (item 2 of argv)\n"
        "end run"
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, body, title], check=False, timeout=10
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 본 분석을 막지 않도록
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="주가 변동 원인을 분석합니다 (투자 권유 아님)."
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        help="종목 코드 (예: TSLA). 생략 시 stdin 에서 읽습니다.",
    )
    parser.add_argument(
        "-q",
        "--question",
        help="티커에 대한 추가 질문 (선택).",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="macOS 알림(display notification)으로 한 줄 요약을 표시합니다.",
    )
    parser.add_argument(
        "--popup",
        action="store_true",
        help="macOS 팝업 창(display dialog)으로 핵심 발췌를 표시합니다.",
    )
    args = parser.parse_args()

    load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "❌ ANTHROPIC_API_KEY 가 설정되지 않았습니다.\n"
            "   .env 파일에 키를 넣어주세요:  ANTHROPIC_API_KEY=sk-ant-...\n"
            "   (.env.example 을 복사해서 사용하세요)",
            file=sys.stderr,
        )
        return 1

    ticker = read_ticker(args.ticker)
    if not ticker:
        print("❌ 티커가 비어 있습니다. 예) python cli.py TSLA", file=sys.stderr)
        return 1

    # agents 모듈은 키 확인 이후에 import (import 시점의 부작용 회피).
    from agents import StockInsightAgent

    print(f"📊 {ticker} 분석 중...", file=sys.stderr)
    try:
        analysis = StockInsightAgent().analyze(ticker, args.question)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 친절한 메시지로 종료
        print(f"❌ 분석 중 오류가 발생했습니다: {exc}", file=sys.stderr)
        return 1

    print(f"\n=== {ticker} 변동 원인 분석 ===\n")
    print(analysis)

    # --notify 와 --popup 은 독립적으로, 둘 다 켤 수 있다.
    if args.notify:
        notify_macos(f"{ticker} 분석 완료", analysis)
    if args.popup:
        popup_macos(f"{ticker} 분석", analysis)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
