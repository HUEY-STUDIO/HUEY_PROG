"""용도지역 정규화 + 국가법령상 건폐율/용적률 상한.

근거 법령
  - 건축법 제55조(건축물의 건폐율), 제56조(건축물의 용적률)
      -> 국토의 계획 및 이용에 관한 법률 제77조·제78조를 따르도록 위임
  - 국토의 계획 및 이용에 관한 법률 시행령 제84조(용도지역 안에서의 건폐율)
  - 국토의 계획 및 이용에 관한 법률 시행령 제85조(용도지역 안에서의 용적률)

중요: 아래 값은 '시행령이 정한 범위(상한)'이며 실제 적용값은 각 지자체
도시계획조례로 이 범위 안에서 따로 정한다. 따라서 이 모듈의 결과는
"법정 상한"이고, 대지에 실제 적용되는 수치는 조례를 확인해야 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ZoneCategory(str, Enum):
    RESIDENTIAL = "주거지역"
    COMMERCIAL = "상업지역"
    INDUSTRIAL = "공업지역"
    GREEN = "녹지지역"
    MANAGEMENT = "관리지역"
    AGRICULTURAL = "농림지역"
    CONSERVATION = "자연환경보전지역"


@dataclass(frozen=True)
class ZoneLimit:
    """용도지역 하나에 대한 법정 상한."""

    code: str  # 내부 정규화 코드
    name: str  # 표준 명칭
    category: ZoneCategory
    building_coverage_max: float  # 건폐율 상한 (%)
    floor_area_ratio_min: float  # 용적률 하한 (%)
    floor_area_ratio_max: float  # 용적률 상한 (%)
    statute_refs: tuple[str, ...] = field(
        default=("국토의 계획 및 이용에 관한 법률 시행령 제84조", "국토의 계획 및 이용에 관한 법률 시행령 제85조")
    )


# 국토계획법 시행령 제84조 / 제85조 기준
ZONE_LIMITS: dict[str, ZoneLimit] = {
    z.code: z
    for z in [
        # --- 주거지역 ---
        ZoneLimit("res_excl_1", "제1종전용주거지역", ZoneCategory.RESIDENTIAL, 50, 50, 100),
        ZoneLimit("res_excl_2", "제2종전용주거지역", ZoneCategory.RESIDENTIAL, 50, 100, 150),
        ZoneLimit("res_gen_1", "제1종일반주거지역", ZoneCategory.RESIDENTIAL, 60, 100, 200),
        ZoneLimit("res_gen_2", "제2종일반주거지역", ZoneCategory.RESIDENTIAL, 60, 100, 250),
        ZoneLimit("res_gen_3", "제3종일반주거지역", ZoneCategory.RESIDENTIAL, 50, 100, 300),
        ZoneLimit("res_semi", "준주거지역", ZoneCategory.RESIDENTIAL, 70, 200, 500),
        # --- 상업지역 ---
        ZoneLimit("com_central", "중심상업지역", ZoneCategory.COMMERCIAL, 90, 400, 1500),
        ZoneLimit("com_general", "일반상업지역", ZoneCategory.COMMERCIAL, 80, 300, 1300),
        ZoneLimit("com_neighbor", "근린상업지역", ZoneCategory.COMMERCIAL, 70, 200, 900),
        ZoneLimit("com_dist", "유통상업지역", ZoneCategory.COMMERCIAL, 80, 200, 1100),
        # --- 공업지역 ---
        ZoneLimit("ind_excl", "전용공업지역", ZoneCategory.INDUSTRIAL, 70, 150, 300),
        ZoneLimit("ind_general", "일반공업지역", ZoneCategory.INDUSTRIAL, 70, 200, 350),
        ZoneLimit("ind_semi", "준공업지역", ZoneCategory.INDUSTRIAL, 70, 200, 400),
        # --- 녹지지역 ---
        ZoneLimit("green_conserv", "보전녹지지역", ZoneCategory.GREEN, 20, 50, 80),
        ZoneLimit("green_prod", "생산녹지지역", ZoneCategory.GREEN, 20, 50, 100),
        ZoneLimit("green_natural", "자연녹지지역", ZoneCategory.GREEN, 20, 50, 100),
        # --- 관리지역 ---
        ZoneLimit("mgmt_conserv", "보전관리지역", ZoneCategory.MANAGEMENT, 20, 50, 80),
        ZoneLimit("mgmt_prod", "생산관리지역", ZoneCategory.MANAGEMENT, 20, 50, 80),
        ZoneLimit("mgmt_plan", "계획관리지역", ZoneCategory.MANAGEMENT, 40, 50, 100),
        # --- 농림 / 자연환경보전 ---
        ZoneLimit("agri", "농림지역", ZoneCategory.AGRICULTURAL, 20, 50, 80),
        ZoneLimit("conserv", "자연환경보전지역", ZoneCategory.CONSERVATION, 20, 50, 80),
    ]
}


# 표준 명칭 및 실무에서 자주 쓰는 축약형 -> 정규화 코드
_ALIASES: dict[str, str] = {
    "제1종전용주거지역": "res_excl_1",
    "1종전용주거": "res_excl_1",
    "제2종전용주거지역": "res_excl_2",
    "2종전용주거": "res_excl_2",
    "제1종일반주거지역": "res_gen_1",
    "1종일반주거": "res_gen_1",
    "제2종일반주거지역": "res_gen_2",
    "2종일반주거": "res_gen_2",
    "제3종일반주거지역": "res_gen_3",
    "3종일반주거": "res_gen_3",
    "준주거지역": "res_semi",
    "중심상업지역": "com_central",
    "일반상업지역": "com_general",
    "근린상업지역": "com_neighbor",
    "유통상업지역": "com_dist",
    "전용공업지역": "ind_excl",
    "일반공업지역": "ind_general",
    "준공업지역": "ind_semi",
    "보전녹지지역": "green_conserv",
    "생산녹지지역": "green_prod",
    "자연녹지지역": "green_natural",
    "보전관리지역": "mgmt_conserv",
    "생산관리지역": "mgmt_prod",
    "계획관리지역": "mgmt_plan",
    "농림지역": "agri",
    "자연환경보전지역": "conserv",
}

# 로마숫자/한글수사로 표기된 '종' 구분을 아라비아 숫자로 통일한다.
# 반드시 '제O종' 문맥 안에서만 치환한다. 문자열 전체에 적용하면
# '일반주거' 의 '일' 까지 '1반주거' 로 망가진다.
_ORDINAL_MAP = {
    "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3",
    "I": "1", "II": "2", "III": "3",
    "일": "1", "이": "2", "삼": "3",
}
_ORDINAL_RE = re.compile(r"제\s*(Ⅰ|Ⅱ|Ⅲ|III|II|I|일|이|삼)\s*종")


def normalize_zone_name(raw: str) -> str | None:
    """LURIS/토지이음 등에서 온 용도지역 문자열을 정규화 코드로 바꾼다.

    실제 응답에는 "제1종일반주거지역", "1종일반주거", "제2종일반주거지역(7층이하)"
    처럼 표기 편차가 크다. 공백/괄호/구분자를 제거한 뒤 별칭 사전과 대조하고,
    정확히 일치하지 않으면 가장 긴 별칭 부분일치로 판정한다.

    Returns:
        정규화 코드, 판정 불가 시 None.
    """
    if not raw:
        return None

    text = str(raw)
    # 괄호 안 부가설명 제거: "제2종일반주거지역(7층이하)" -> "제2종일반주거지역"
    text = re.sub(r"[(（\[].*?[)）\]]", "", text)
    text = _ORDINAL_RE.sub(lambda m: f"제{_ORDINAL_MAP[m.group(1)]}종", text)
    # 공백/구분자 제거
    text = re.sub(r"[\s·,/\-_]+", "", text)

    if text in _ALIASES:
        return _ALIASES[text]

    # 부분일치. 짧은 별칭이 긴 이름에 먼저 걸리지 않도록 긴 것부터 본다.
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in text:
            return _ALIASES[alias]
    return None


def lookup_limit(raw_zone_name: str) -> ZoneLimit | None:
    """용도지역 명칭으로 법정 상한을 조회한다. 판정 실패 시 None."""
    code = normalize_zone_name(raw_zone_name)
    return ZONE_LIMITS.get(code) if code else None


def all_limits() -> list[ZoneLimit]:
    return list(ZONE_LIMITS.values())
