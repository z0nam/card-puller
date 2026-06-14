"""카드사 어댑터 레지스트리.

새 카드사 추가: CardAdapter 서브클래스를 만들고 아래 ADAPTERS 에 등록하면
`card --issuer <name>` 으로 바로 쓸 수 있다. (CONTRIBUTING.md 참고)
"""

from __future__ import annotations

from .base import (
    CardAdapter,
    Period,
    TabInfo,
    NORMALIZED_COLUMNS,
    CDP_ENDPOINT,
    prev_month_period,
    month_period,
)
from .hyundai import HyundaiAdapter

# name → 어댑터 클래스
ADAPTERS: dict[str, type[CardAdapter]] = {
    HyundaiAdapter.name: HyundaiAdapter,
}


def available() -> list[str]:
    return list(ADAPTERS)


def get_adapter(name: str) -> type[CardAdapter]:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise SystemExit(
            f"알 수 없는 카드사 '{name}'. 사용 가능: {', '.join(available())}"
        )


__all__ = [
    "CardAdapter", "Period", "TabInfo", "NORMALIZED_COLUMNS", "CDP_ENDPOINT",
    "prev_month_period", "month_period", "HyundaiAdapter",
    "ADAPTERS", "available", "get_adapter",
]
