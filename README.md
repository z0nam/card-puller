# card-puller

> 내가 직접 로그인한 카드사 세션에 붙어, 내 카드 이용내역을 받아 정규화하고 실비 증빙까지
> 만드는 로컬 도구. (Attach to your *own* logged-in card session, normalize your
> transactions locally, and generate expense receipts. No credentials stored, no auto-login.)

한국 카드사 웹사이트는 보안 모듈 때문에 새로 띄운 자동화 브라우저 로그인이 잘 막힙니다.
이 도구는 로그인을 자동화하지 않습니다. **당신이 평소처럼 직접 로그인해 둔 크롬**에
CDP로 attach해서, 이미 인증된 세션으로 *당신의* 데이터만 조회/다운로드합니다.

현재 지원: **현대카드**. 다른 카드사는 어댑터를 추가해 끼울 수 있습니다 → [CONTRIBUTING.md](CONTRIBUTING.md).

## ⚠️ 고지 (읽고 쓰세요)

- **개인 본인용 도구입니다.** 본인 계정의 본인 데이터를 조회/다운로드하는 용도에 한정합니다.
- 카드사 웹사이트 **이용약관의 자동 접근 조항은 사용자 본인 책임**입니다. 과도한 반복 폴링
  금지, "내 데이터 조회/다운로드"로만 쓰세요.
- 한국에는 정식 경로로 **마이데이터(MyData) API**가 있습니다. 사업/대량/상시 연동이
  목적이라면 그쪽이 맞습니다. (마이데이터 *사업자*에게는 스크래핑이 금지되어 있습니다.)
- 내부 응답 포맷에 의존하므로 **카드사가 사이트를 바꾸면 깨질 수 있습니다.**
- **무보증(AS-IS).** [LICENSE](LICENSE) 참고. 자격증명은 어디에도 저장하지 않으며, 받은
  데이터는 전부 로컬(`data/`, git 제외)에만 둡니다.

## 설치

```bash
uv venv --python 3.12 .venv          # 또는 python3.12 -m venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m playwright install chromium
```

## 사용법

### 0) 직접 로그인 (사람이)

```bash
./launch_chrome_cdp.sh               # 디버깅 포트(9222) + 전용 프로필로 크롬 실행
# 뜬 크롬에서 카드사 사이트에 직접 로그인 (앱 QR/인증서/OTP 전부 수동)
```
Chrome 136+ 는 기본 프로필에선 디버깅 포트를 무시하므로 **전용 프로필이 필요**합니다(런처가 처리).

### 1) `card` CLI

```bash
./card check                  # 로그인/attach 상태 점검
./card pull [YYYYMM]          # 이용내역 받아 정규화 + 해외 실비 리포트 (기본: 전월)
./card evidence [YYYYMM]      # 해외 결제 매출전표 PDF 증빙 추출 (기본: 전월)

./card --issuer hyundai pull 202605   # 카드사 명시 (기본 hyundai)
```
한글 별칭: `card 체크`, `card 받기`, `card 증빙`. 자주 쓰면 `alias card="$PWD/card"`.

산출물 (모두 `data/`, git 제외):
- `data/normalized/<issuer>_settled_<YYYYMM>.{parquet,csv}` — 정규화 테이블
- `data/normalized/foreign_expense_<YYYYMM>.csv` — 해외 실비 요약
- `data/evidence/receipt_*.pdf` (+ 합본) — 결재 제출용 매출전표 증빙

## 정규 스키마

모든 어댑터의 `parse()`는 아래 동일 스키마를 produce합니다.

| 필드 | 설명 |
|---|---|
| tx_date | 거래/승인일 (YYYY-MM-DD) |
| merchant | 가맹점명 |
| amount_krw | 국내 청구금액(원) — 국내건 |
| amount_foreign | 해외 원통화 금액 — 해외건 |
| currency | 해외 통화코드 |
| amount_krw_billed | 해외 원화 환산 청구금액 (매입확정 시에만) |
| fx_rate | 적용 환율 |
| settle_status | 매입확정 / 승인(미매입) / 취소 |
| category | 카드사 제공 분류 |
| raw_row | 원본 행 보존 (JSON 문자열) |

> **해외결제 주의:** 원화 환산 청구금액은 **매입 확정 후에만 확정**됩니다. 승인(미매입)
> 건은 `amount_krw_billed`를 비워두고 `settle_status`로 구분합니다 — 실비 청구는 확정된
> 금액만 해야 정확합니다.

## 구조

```
adapters/
  base.py       # 공통 인프라(attach/세션점검) + CardAdapter 인터페이스 + 정규 스키마
  hyundai.py    # 현대카드 구현체
  __init__.py   # 어댑터 레지스트리 (name → class)
card.py         # CLI (check / pull / evidence, --issuer)
card            # 실행 래퍼
launch_chrome_cdp.sh
```

새 카드사 추가는 [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

## 동작 메모 (현대카드)

- 이용내역 페이지의 조회 버튼이 AJAX로 JSON을 반환 → 엑셀보다 깨끗하고 해외 통화/환율/국가
  필드까지 포함하므로 JSON을 1차 소스로 사용(엑셀도 함께 보존).
- 과거 월 데이터는 '결제확정' 뷰에만 있음('실시간승인'은 최근 미매입만).
- 증빙은 거래별 매출전표 팝업을 캡처해 PDF로 묶음.

## 개발 환경

Python 3.12, Playwright, pandas/pyarrow/openpyxl, lxml, img2pdf. macOS 기준.
