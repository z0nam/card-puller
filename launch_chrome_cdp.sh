#!/usr/bin/env bash
# 카드사 attach 용 크롬을 디버깅 포트(9222)로 띄운다.
# 자동 로그인은 하지 않는다 — 이 크롬에서 사람이 직접 로그인한다.
#
# 주의: 기본 크롬 프로필은 이미 떠 있으면(그리고 Chrome 136+는 기본 프로필 자체에서)
# 디버깅 포트가 안 열린다. 그래서 전용 프로필 디렉터리를 따로 쓴다
# (로그인은 이 프로필에서 한 번 직접).
#
# 사용: ./launch_chrome_cdp.sh [열고싶은_URL]
set -euo pipefail

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE="$HOME/chrome-cdp-profile"
PORT=9222
URL="${1:-https://www.hyundaicard.com}"   # 기본: 현대카드. 다른 카드사면 URL 인자로.

if [[ ! -x "$CHROME" ]]; then
  echo "크롬을 찾을 수 없음: $CHROME" >&2
  exit 1
fi

echo "크롬을 디버깅 포트 $PORT 로 띄웁니다 (프로필: $PROFILE)"
echo "→ 이 창에서 카드사 사이트에 직접 로그인한 뒤, 다른 터미널에서:"
echo "    ./card check    (또는 ./card pull / ./card evidence)"
echo

exec "$CHROME" \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  "$URL"
