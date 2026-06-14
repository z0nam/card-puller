#!/usr/bin/env python3
"""card — 카드 이용내역 수집/정규화/증빙 CLI.

전제: 디버깅 포트(`--remote-debugging-port=9222`) 크롬에서 카드사 사이트에 직접
로그인해 둔 상태. 자동 로그인은 구현하지 않는다(설계 원칙).

  card check                     # 로그인/attach 상태 점검
  card pull [YYYYMM]             # 이용내역 받아 정규화 + 해외 실비 리포트 (기본: 전월)
  card evidence [YYYYMM]         # 해외 결제 매출전표 PDF 증빙 추출 (기본: 전월)

  --issuer <name>  카드사 선택 (기본: hyundai). 예: card --issuer hyundai pull 202605
  한글 별칭: check=체크, pull=받기, evidence=증빙
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from adapters import CardAdapter, available, get_adapter, month_period, prev_month_period

RAW = Path("data/raw")
NORM = Path("data/normalized")
EVID = Path("data/evidence")


def _period(month: str | None):
    return month_period(month) if month else prev_month_period(date.today())


def _new(issuer: str) -> CardAdapter:
    adapter = get_adapter(issuer)()
    adapter.attach()  # 실패 시 ConnectionError → main()에서 처리
    return adapter


# ---------- check ----------
def cmd_check(issuer: str, _month=None) -> int:
    a = _new(issuer)
    tabs = a.list_tabs()
    page = a.find_card_page()
    print(f"[{a.display_name}] 열린 탭 {len(tabs)}개, 카드사 탭: {'있음' if page else '없음'}")
    if page is None:
        print(f"⚠️ {a.display_name} 탭 없음 — 디버깅 포트 크롬에서 로그인 필요.")
        a.close(); return 1
    st = a.check_login(page)
    print(f"URL: {page.url}\n로그인 추정: {st.get('verdict')}  "
          f"{st.get('logged_in_hints', st.get('reason', ''))}")
    ok = st.get("verdict") == "logged_in"
    print("✅ 준비 완료 (pull/evidence 실행 가능)" if ok else "⚠️ 로그인 확인 필요")
    a.close(); return 0 if ok else 1


# ---------- pull ----------
def cmd_pull(issuer: str, month=None) -> int:
    period = _period(month)
    a = _new(issuer)
    print(f"[{a.display_name}] pull {period.start} ~ {period.end}")
    try:
        art = a.download(period, RAW)
    except RuntimeError as e:
        print(f"❌ {e}"); a.close(); return 1
    a.close()
    if not art.get("json"):
        print("❌ 받은 데이터 없음."); return 1

    NORM.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    frames = []
    for jf in art["json"]:
        df = a.parse(jf)
        df.to_parquet(NORM / f"{jf.stem}.parquet", index=False)
        df.to_csv(NORM / f"{jf.stem}.csv", index=False, encoding="utf-8-sig")
        frames.append(df)
        print(f"  정규화 {jf.stem}: {len(df)}건")

    alldf = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    fx = alldf[alldf["currency"].notna()].copy() if not alldf.empty else alldf
    if not fx.empty:
        dest = NORM / f"foreign_expense_{period.label}.csv"
        fx[["tx_date", "merchant", "currency", "amount_foreign", "fx_rate",
            "amount_krw_billed", "settle_status"]].sort_values("tx_date").to_csv(
            dest, index=False, encoding="utf-8-sig")
        conf = int(fx["amount_krw_billed"].dropna().sum())
        print(f"  해외 {len(fx)}건, 원화확정 합계 {conf:,}원 → {dest.name}")
    print("✅ pull 완료. data/normalized/ 확인.")
    return 0


# ---------- evidence ----------
def cmd_evidence(issuer: str, month=None) -> int:
    period = _period(month)
    a = _new(issuer)
    print(f"[{a.display_name}] evidence(해외 매출전표) {period.start} ~ {period.end}")
    try:
        pngs = a.capture_evidence(period, EVID, foreign_only=True)
    except RuntimeError as e:
        print(f"❌ {e}"); a.close(); return 2
    a.close()
    if not pngs:
        print("해외 결제건 없음 — 추출할 전표 없음."); return 0

    import img2pdf
    combined = EVID / f"{issuer}_foreign_evidence_{period.label}.pdf"
    with open(combined, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in pngs]))
    for p in pngs:
        with open(p.with_suffix(".pdf"), "wb") as f:
            f.write(img2pdf.convert(str(p)))
        print(f"  ✅ {p.with_suffix('.pdf').name}")
    print(f"✅ 개별 {len(pngs)}건 + 합본({combined.name}) → {EVID}/")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="card", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--issuer", default="hyundai",
                   help=f"카드사 (기본: hyundai). 사용 가능: {', '.join(available())}")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", aliases=["체크"], help="로그인/attach 점검")
    c.set_defaults(func=cmd_check)

    pl = sub.add_parser("pull", aliases=["sync", "get", "받기"],
                        help="받기 + 정규화 + 해외 실비 리포트")
    pl.add_argument("month", nargs="?", help="YYYYMM (기본: 전월)")
    pl.set_defaults(func=cmd_pull)

    ev = sub.add_parser("evidence", aliases=["증빙", "receipts"],
                        help="해외 결제 매출전표 PDF 증빙")
    ev.add_argument("month", nargs="?", help="YYYYMM (기본: 전월)")
    ev.set_defaults(func=cmd_evidence)
    return p


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        return args.func(args.issuer, getattr(args, "month", None))
    except ConnectionError as e:
        print(f"❌ attach 실패: {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
