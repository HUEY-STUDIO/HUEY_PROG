"""공공 API 응답 파싱 공통 헬퍼.

같은 정보라도 서비스/버전에 따라 필드명이 다르게 오는 일이 잦아
(``lndcgrCodeNm`` vs ``lndcgrNm``), 후보 키를 순서대로 훑는 방식을 쓴다.
"""

from __future__ import annotations

from typing import Any

_EMPTY = (None, "", " ")


def pick_field(record: dict[str, Any], *keys: str) -> Any:
    """후보 키 중 먼저 발견되는 비어있지 않은 값을 반환. 없으면 None."""
    for key in keys:
        value = record.get(key)
        if value not in _EMPTY:
            return value
    return None


def to_float(value: Any) -> float | None:
    """천단위 콤마가 섞인 문자열도 처리하는 float 변환. 실패 시 None."""
    if value in _EMPTY:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def to_int(value: Any) -> int | None:
    result = to_float(value)
    return int(result) if result is not None else None
