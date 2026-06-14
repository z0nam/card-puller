"""Card adapter 공통 인프라 + 어댑터 인터페이스.

설계 철학 (모든 어댑터 공통):
- **자동 로그인을 구현하지 않는다.** 로그인/인증서/간편인증/OTP는 사용자가 직접 한다.
- **새 자동화 브라우저를 띄우지 않는다.** 사용자가 `--remote-debugging-port`로 직접 띄워
  로그인해 둔 실제 크롬에 CDP로 attach 하여 "내가 인증한 세션을 이어받기"만 한다.
  (많은 한국 금융 사이트의 보안 모듈이 새로 띄운 자동화 브라우저를 막기 때문에,
   이미 인증된 내 세션에 붙는 방식이 안정적이다.)
- **자격증명(ID/PW/인증서)을 코드·설정·로그 어디에도 저장하지 않는다.**

새 카드사 추가법: `CardAdapter`를 상속해 `host_hints`와 4개 추상 메서드
(`goto_statements`/`download`/`parse`/`capture_evidence`)를 구현하고
`adapters/__init__.py`의 레지스트리에 등록한다. 자세한 건 CONTRIBUTING.md.
"""

from __future__ import annotations

import abc
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

# 사용자가 크롬을 띄운 CDP 디버깅 엔드포인트.
CDP_ENDPOINT = "http://localhost:9222"

# 모든 어댑터의 parse()가 반드시 produce 해야 하는 정규 스키마(출력 계약).
NORMALIZED_COLUMNS = [
    "tx_date",            # 거래/승인일 (YYYY-MM-DD)
    "merchant",           # 가맹점명
    "amount_krw",         # 국내 청구금액(원) — 국내건
    "amount_foreign",     # 해외 원통화 금액 — 해외건
    "currency",           # 해외 통화코드
    "amount_krw_billed",  # 해외 원화 환산 청구금액 (매입확정 시에만 채움)
    "fx_rate",            # 적용 환율
    "settle_status",      # 매입확정 / 승인(미매입) / 취소
    "category",           # 카드사 제공 분류
    "raw_row",            # 원본 행 보존 (JSON 문자열)
]
# pandas nullable 정수로 둘 컬럼.
INT_COLUMNS = ("amount_krw", "amount_krw_billed")


@dataclass
class Period:
    """조회 기간. start/end 는 date, 사이트 제출용 문자열도 제공."""

    start: date
    end: date

    @property
    def ymd_start(self) -> str:
        return self.start.strftime("%Y%m%d")

    @property
    def ymd_end(self) -> str:
        return self.end.strftime("%Y%m%d")

    @property
    def label(self) -> str:
        return self.start.strftime("%Y%m")

    @property
    def dotted_start(self) -> str:
        return f"{self.start.year}. {self.start.month}. {self.start.day}"

    @property
    def dotted_end(self) -> str:
        return f"{self.end.year}. {self.end.month}. {self.end.day}"


def prev_month_period(today: date) -> Period:
    """today 기준 전월 1일~말일."""
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    start = last_prev.replace(day=1)
    end = last_prev.replace(day=calendar.monthrange(last_prev.year, last_prev.month)[1])
    return Period(start, end)


def month_period(yyyymm: str) -> Period:
    """'YYYYMM' → 그 달 1일~말일."""
    y, m = int(yyyymm[:4]), int(yyyymm[4:6])
    return Period(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]))


@dataclass
class TabInfo:
    index: int
    url: str
    title: str
    is_card: bool  # 이 어댑터의 host_hints 에 해당하는 탭인지


class CardAdapter(abc.ABC):
    """카드사 어댑터 베이스.

    공통(attach/close/list_tabs/find_card_page/check_login)은 여기서 구현하고,
    카드사별 사이트 조작(goto_statements/download/parse/capture_evidence)은 추상으로
    남겨 서브클래스가 채운다.
    """

    # ----- 어댑터별로 오버라이드하는 메타 -----
    name: str = ""                       # CLI 식별자 (예: "hyundai")
    display_name: str = ""               # 사람용 이름 (예: "현대카드")
    host_hints: tuple[str, ...] = ()     # 도메인 조각 (예: ("hyundaicard.com",))
    # 로그인 상태를 가늠하는 텍스트 힌트(휴리스틱). 한 글자 힌트는 오탐 → 피한다.
    logged_in_hints: tuple[str, ...] = ("로그아웃", "logout", "마이페이지")
    logged_out_hints: tuple[str, ...] = ("로그인", "login", "인증서 로그인")
    # 로그인 판정을 신뢰할 수 없는 페이지(설치/안내 등) URL 조각.
    non_session_url_hints: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self.browser: Optional[Browser] = None

    # ----- 공통: attach / 세션 점검 -----
    def attach(self) -> Browser:
        """이미 떠 있는 크롬에 CDP로 붙는다. 새 브라우저를 만들지 않는다."""
        self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        except Exception as e:
            self._pw.stop()
            self._pw = None
            raise ConnectionError(
                f"CDP attach 실패: {CDP_ENDPOINT} 에 붙을 수 없음.\n"
                f"크롬을 --remote-debugging-port 로 띄우고 로그인했는지 확인하세요.\n"
                f"원인: {e}"
            ) from e
        return self.browser

    def list_tabs(self) -> list[TabInfo]:
        tabs: list[TabInfo] = []
        idx = 0
        for context in self.browser.contexts:
            for page in context.pages:
                url = page.url or ""
                try:
                    title = page.title()
                except Exception:
                    title = "(title 읽기 실패)"
                tabs.append(TabInfo(idx, url, title, self._is_card_url(url)))
                idx += 1
        return tabs

    def _is_card_url(self, url: str) -> bool:
        return any(h in (url or "") for h in self.host_hints)

    def find_card_page(self) -> Optional[Page]:
        """이 카드사 도메인 탭 중 첫 번째를 돌려준다. 새 탭을 만들지 않는다."""
        for context in self.browser.contexts:
            for page in context.pages:
                if self._is_card_url(page.url or ""):
                    return page
        return None

    def check_login(self, page: Page) -> dict:
        """로그인 상태를 페이지 텍스트 힌트로 휴리스틱 추정한다(확정 아님)."""
        url = (page.url or "").lower()
        if any(h in url for h in self.non_session_url_hints):
            return {
                "verdict": "non_session_page",
                "reason": "설치/안내 페이지라 판정 불가. 로그인 후 마이페이지/이용내역에서 재확인.",
            }
        try:
            body = page.inner_text("body", timeout=5000)
        except Exception as e:
            return {"verdict": "unknown", "reason": f"본문 텍스트 읽기 실패: {e}"}

        low = body.lower()
        found_in = [h for h in self.logged_in_hints if h.lower() in low]
        found_out = [h for h in self.logged_out_hints if h.lower() in low]
        if found_in and not found_out:
            verdict = "logged_in"
        elif found_out and not found_in:
            verdict = "logged_out"
        elif found_in and found_out:
            verdict = "ambiguous"
        else:
            verdict = "unknown"
        return {
            "verdict": verdict,
            "logged_in_hints": found_in,
            "logged_out_hints": found_out,
            "text_len": len(body),
        }

    def close(self) -> None:
        """CDP 연결만 정리하고 사용자의 실제 크롬은 살려둔다.
        (connect_over_cdp 의 close()는 원격 브라우저 프로세스를 종료하지 않는다.)
        """
        try:
            if self.browser is not None:
                self.browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
                self._pw = None
            self.browser = None

    # ----- 공통: 정규화 헬퍼 -----
    @staticmethod
    def _num(x) -> Optional[float]:
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _finalize(cls, rows: list[dict]):
        """행 dict 리스트를 정규 스키마 DataFrame(dtype/정렬 적용)으로 만든다."""
        import pandas as pd

        df = pd.DataFrame(rows, columns=NORMALIZED_COLUMNS)
        if not df.empty:
            for c in INT_COLUMNS:
                df[c] = df[c].astype("Int64")
            df = df.sort_values("tx_date").reset_index(drop=True)
        return df

    # ----- 어댑터별 구현 (추상) -----
    @abc.abstractmethod
    def goto_statements(self, period: Period) -> Page:
        """열린 카드사 탭을 이용내역 조회 페이지로 이동시킨다(새 탭 금지)."""

    @abc.abstractmethod
    def download(self, period: Period, out_dir: Optional[Path] = None) -> dict:
        """기간 이용내역을 받아 data/raw 등에 저장. 반환: {"json":[...], "xls":[...]} 등."""

    @abc.abstractmethod
    def parse(self, path: Path):
        """원본 파일을 NORMALIZED_COLUMNS 스키마 DataFrame으로 변환한다."""

    @abc.abstractmethod
    def capture_evidence(self, period: Period, out_dir: Path, foreign_only: bool = True) -> list[Path]:
        """거래별 매출전표/영수증을 캡처해 증빙 이미지(PNG) 경로 리스트를 돌려준다."""
