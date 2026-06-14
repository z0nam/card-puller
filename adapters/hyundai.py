"""현대카드(Hyundai Card) 어댑터.

공통 설계 철학은 adapters/base.py 참고 (자동 로그인 없음 / attach로 내 세션 이어받기 /
자격증명 미저장). 이 파일은 현대카드 사이트 특화 조작만 담는다.

핵심 데이터 경로:
- 이용내역 페이지의 조회 버튼 goFilter()가 AJAX(apiCPACB0101_*)로 JSON을 준다.
  이 JSON이 엑셀보다 깨끗하고 해외 통화/환율/국가 필드까지 포함 → 1차 데이터 소스.
- 과거 월 데이터는 '결제확정'(listClsf=1) 뷰에만 있다. '실시간승인'(0)은 최근 미매입만.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page

from .base import CardAdapter, Period


class HyundaiAdapter(CardAdapter):
    name = "hyundai"
    display_name = "현대카드"
    host_hints = ("hyundaicard.com",)
    logged_in_hints = ("로그아웃", "logout", "마이페이지", "MY현대카드")
    logged_out_hints = ("로그인", "login", "아이디 저장", "인증서 로그인")
    non_session_url_hints = ("veraport", "install", "wizvera", "solution/")

    # 이용내역(최근 이용내역) 페이지.
    STATEMENTS_URL = "https://www.hyundaicard.com/cpa/cb/CPACB0101_01.hc"
    # 세션이 끊겼을 때 전표 팝업/응답에 나타나는 문구.
    NOT_LOGGED_IN = "로그인 상태가 아닙니다"

    # ----- 이용내역 도달 -----
    def goto_statements(self, period: Period) -> Page:
        page = self.find_card_page()
        if page is None:
            raise RuntimeError(
                "현대카드 탭이 없습니다. 디버깅 포트 크롬에서 로그인 후 다시 시도하세요."
            )
        if not page.url.endswith("CPACB0101_01.hc"):
            page.goto(self.STATEMENTS_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
        if page.query_selector("#form1 #iqrySrtDt") is None:
            raise RuntimeError(f"이용내역 폼을 찾지 못함(세션 만료 가능). 현재 URL: {page.url}")
        return page

    def _set_period_and_view(self, page: Page, period: Period, settled: bool) -> None:
        """조회 폼 기간을 '직접입력'으로 맞추고 listClsf(승인/확정)·zoneClsf(전체) 설정."""
        page.evaluate(
            """({srt, end, dotSrt, dotEnd, settled}) => {
                const direct = document.getElementById('dtClsf_04');   // 직접입력(val=9)
                if (direct) direct.checked = true;
                ['dtClsf_01','dtClsf_02','dtClsf_03','dtClsf_05']
                    .forEach(id => { const e=document.getElementById(id); if(e) e.checked=false; });
                const set = (id,v)=>{const e=document.getElementById(id); if(e) e.value=v;};
                set('iqrySrtDt', srt); set('iqryEndDt', end);   // 실제 제출되는 숨은 날짜
                set('srtDt', dotSrt);  set('endDt', dotEnd);    // 보이는 날짜
                const zall=document.getElementById('zoneClsf_01'); if(zall) zall.checked=true; // 국내+해외 전체
                ['zoneClsf_02','zoneClsf_03'].forEach(id=>{const e=document.getElementById(id); if(e) e.checked=false;});
                const a=document.getElementById('listClsf_01'); // 실시간 승인
                const b=document.getElementById('listClsf_02'); // 결제 확정
                if(a) a.checked = !settled;
                if(b) b.checked = settled;
            }""",
            {
                "srt": period.ymd_start, "end": period.ymd_end,
                "dotSrt": period.dotted_start, "dotEnd": period.dotted_end,
                "settled": settled,
            },
        )

    def query(self, page: Page, period: Period, settled: bool) -> Optional[dict]:
        """goFilter()로 조회하고 AJAX 응답(JSON)을 가로채 돌려준다.
        settled=True → 결제확정(apiCPACB0101_22), False → 실시간승인(apiCPACB0101_21)."""
        self._set_period_and_view(page, period, settled)
        page.wait_for_timeout(200)
        list_clsf = "1" if settled else "0"
        try:
            with page.expect_response(lambda r: "apiCPACB0101" in r.url, timeout=20000) as resp_info:
                page.evaluate(f"window.goFilter && window.goFilter('{list_clsf}')")
            return resp_info.value.json()
        except Exception as e:
            print(f"  ⚠️ 조회 AJAX 캡처 실패: {e}")
            return None

    @staticmethod
    def _items(j: Optional[dict]) -> list[dict]:
        return ((j or {}).get("bdy", {}) or {}).get("acqrUseItmList") or []

    # ----- 다운로드 -----
    def download(self, period: Period, out_dir: Optional[Path] = None) -> dict:
        """이용내역을 받는다. 1차: 조회 AJAX JSON(견고), 2차: excelAction() xls(보존).
        과거 월은 결제확정만, 현재월 포함 시 실시간승인도 받는다."""
        out_dir = out_dir or Path("data/raw")
        out_dir.mkdir(parents=True, exist_ok=True)
        page = self.goto_statements(period)

        include_approved = period.end >= date.today().replace(day=1)
        views = [(True, "settled")] + ([(False, "approved")] if include_approved else [])

        artifacts: dict = {"json": [], "xls": []}
        for settled, tag in views:
            j = self.query(page, period, settled)
            if j is not None:
                jpath = out_dir / f"hyundai_{tag}_{period.label}.json"
                jpath.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts["json"].append(jpath)
                print(f"  ✅ {tag} JSON: {jpath}  ({len(self._items(j))}건)")

            page.wait_for_timeout(300)
            try:
                with page.expect_download(timeout=15000) as dl_info:
                    page.evaluate("window.excelAction && window.excelAction()")
                dl = dl_info.value
                ext = Path(dl.suggested_filename or "x.xls").suffix or ".xls"
                xpath = out_dir / f"hyundai_{tag}_{period.label}{ext}"
                dl.save_as(str(xpath))
                artifacts["xls"].append(xpath)
                print(f"  ✅ {tag} XLS:  {xpath}")
            except Exception as e:
                print(f"  ⚠️ {tag} 엑셀 다운로드 건너뜀: {str(e)[:80]}")
        return artifacts

    # ----- 정규화 -----
    @staticmethod
    def _is_foreign(it: dict) -> bool:
        def num(x):
            try:
                return float(x or 0)
            except (TypeError, ValueError):
                return 0.0
        return bool(
            (it.get("crncCd") or "").strip()
            or (it.get("bllCrncCd") or "").strip()
            or num(it.get("bllFrcrAmt"))
            or str(it.get("useClsf")) == "4"
        )

    def parse(self, path: Path):
        """결제확정/실시간승인 JSON → 정규 스키마 DataFrame.
        파일명에 'approved'가 있으면 승인(미매입), 아니면 매입확정으로 본다."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        items = self._items(raw)
        settled = "approved" not in Path(path).name

        def to_date(ymd: str):
            ymd = (ymd or "").strip()
            return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if len(ymd) == 8 else None

        rows = []
        for it in items:
            fx = self._is_foreign(it)
            amt = self._num(it.get("useAmt"))
            cancelled = it.get("cancYn") == "Y"
            status = "취소" if cancelled else ("매입확정" if settled else "승인(미매입)")
            rows.append({
                "tx_date": to_date(it.get("useDt")),
                "merchant": (it.get("mrchNm") or "").strip(),
                "amount_krw": (None if fx else amt),
                "amount_foreign": (self._num(it.get("bllFrcrAmt")) if fx else None),
                "currency": ((it.get("crncCd") or it.get("bllCrncCd") or "").strip() or None) if fx else None,
                # 해외 원화 환산액은 매입확정 시에만 확정 → 미매입/취소면 비움.
                "amount_krw_billed": (amt if (fx and settled and not cancelled) else None),
                "fx_rate": (self._num(it.get("bllPrcpAplyExrt")) if fx else None),
                "settle_status": status,
                "category": (it.get("mccbLclNm") or "").strip() or None,
                "raw_row": json.dumps(it, ensure_ascii=False),
            })
        return self._finalize(rows)

    # ----- 증빙 (매출전표 캡처) -----
    def capture_evidence(self, period: Period, out_dir: Path, foreign_only: bool = True) -> list[Path]:
        """거래별 매출전표 팝업(popReceipt09)을 캡처해 PNG 경로 리스트를 돌려준다.
        해외건은 가맹점명 하드코딩 대신 조회 JSON의 통화 필드(_is_foreign)로 동적 판별."""
        out_dir.mkdir(parents=True, exist_ok=True)
        page = self.goto_statements(period)
        j = self.query(page, period, settled=True)
        if not j:
            raise RuntimeError("조회 실패 (세션/네트워크 확인)")
        items = self._items(j)
        wanted = {(it.get("mrchNm") or "").strip()
                  for it in items if (not foreign_only or self._is_foreign(it))}
        wanted.discard("")
        if not wanted:
            return []

        rows = page.eval_on_selector_all(
            "a[onclick*=popReceipt09]",
            r"""els=>els.map(e=>({id:e.id, t:(e.innerText||'').replace(/\s+/g,' ').trim()}))""",
        )
        targets = [r for r in rows if any(w and w in r["t"] for w in wanted)]

        def slug(s: str) -> str:
            s = re.sub(r"\s+", "_", s.strip())
            return re.sub(r"[^0-9A-Za-z가-힣._-]", "", s)[:40]

        pngs: list[Path] = []
        for i, r in enumerate(targets, 1):
            rid = r["id"]
            page.evaluate(f"popSeting('{rid}'); popup.open('popReceipt09','{rid}');")
            page.wait_for_timeout(2200)
            pop = page.query_selector("#popReceipt09")
            txt = (pop.inner_text() if pop else "") or ""
            if self.NOT_LOGGED_IN in txt or "자동 로그아웃" in page.inner_text("body"):
                raise RuntimeError(
                    f"세션 만료('{self.NOT_LOGGED_IN}'). 앱 QR 등으로 재로그인 후 다시 시도하세요."
                )
            merch = re.search(r"[A-Za-z][A-Za-z0-9./ ]+", r["t"])
            mname = slug(merch.group(0)) if merch else f"tx{i}"
            dm = re.search(r"\d{2}\.\s*\d{1,2}\.\s*\d{1,2}", r["t"])
            d = slug(dm.group(0)) if dm else f"{i:02d}"
            target = page.query_selector(
                "#popReceipt09 .layer_wrap, #popReceipt09 .modal_container, #popReceipt09 .pop_wrap"
            ) or pop
            png = out_dir / f"receipt_{period.label}_{i:02d}_{d}_{mname}.png"
            target.screenshot(path=str(png))
            pngs.append(png)
            page.evaluate("try{popup.close&&popup.close('popReceipt09')}catch(e){}")
            page.keyboard.press("Escape")
            page.wait_for_timeout(700)
        return pngs
