# 기여 가이드 — 새 카드사 어댑터 추가하기

card-puller는 어댑터 패턴이라, 카드사 하나당 파일 하나를 추가하면 같은 CLI로 굴러갑니다.
현대카드(`adapters/hyundai.py`)를 참고 구현으로 보세요.

## 절차

1. **`adapters/<issuer>.py`** 생성, `CardAdapter` 상속:

   ```python
   from .base import CardAdapter, Period

   class SamsungAdapter(CardAdapter):
       name = "samsung"                       # CLI 식별자 (card --issuer samsung)
       display_name = "삼성카드"
       host_hints = ("samsungcard.com",)      # 탭 식별용 도메인 조각
       logged_in_hints = ("로그아웃", "마이페이지")   # (선택) 로그인 판정 힌트
       logged_out_hints = ("로그인",)
       non_session_url_hints = ()             # (선택) 로그인 판정 불가 페이지 URL 조각
   ```

2. **추상 메서드 4개 구현:**
   - `goto_statements(period)` — 열린 탭을 이용내역 조회 페이지로 이동(새 탭 만들지 말 것).
   - `download(period, out_dir)` — 기간 내역을 받아 `out_dir`에 저장. `{"json":[...], "xls":[...]}` 류 반환.
   - `parse(path)` — 받은 파일을 **정규 스키마**(`base.NORMALIZED_COLUMNS`) DataFrame으로.
     행 dict 리스트를 만들어 `self._finalize(rows)`에 넘기면 dtype/정렬을 맞춰줍니다.
   - `capture_evidence(period, out_dir, foreign_only)` — 거래별 매출전표/영수증을 캡처해
     PNG 경로 리스트 반환(증빙용). 해당 기능이 없으면 `return []`.

   `attach()`/`close()`/`list_tabs()`/`find_card_page()`/`check_login()`은 베이스에 이미
   구현돼 있으니 그대로 씁니다.

3. **레지스트리 등록** — `adapters/__init__.py`:
   ```python
   from .samsung import SamsungAdapter
   ADAPTERS = {HyundaiAdapter.name: HyundaiAdapter, SamsungAdapter.name: SamsungAdapter}
   ```

4. **확인:**
   ```bash
   card --issuer samsung check      # attach + 로그인 점검부터
   card --issuer samsung pull
   ```

## 설계 원칙 (반드시 지킬 것)

- **자동 로그인 금지.** 로그인/인증서/간편인증/OTP는 사용자가 직접. 코드는 이미 인증된
  세션에 attach만 한다.
- **새 자동화 브라우저 금지.** 사용자가 디버깅 포트로 띄운 실제 크롬의 열린 탭을 쓴다.
- **자격증명 미저장.** ID/PW/인증서를 코드·설정·로그에 두지 않는다.
- **셀렉터 추측 하드코딩 지양.** 살아있는 DOM/네트워크 응답을 읽어 경로를 찾는다.
- **개인정보는 `data/`에.** `.gitignore`로 커밋 제외된다.

## 정규 스키마 (`parse()` 출력 계약)

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
