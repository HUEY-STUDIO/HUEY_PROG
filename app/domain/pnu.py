"""PNU(필지고유번호) 조립/해석.

PNU 는 19자리 고정 길이 코드로, 대부분의 국토교통부 계열 오픈API 가
필지를 식별하는 기본 키로 사용한다.

    법정동코드(10) + 필지구분(1) + 본번(4) + 부번(4) = 19

  - 법정동코드: 시도(2) 시군구(3) 읍면동(3) 리(2)
  - 필지구분: 1 = 일반(토지), 2 = 산(임야)
  - 본번/부번: 각각 4자리 0-padding
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PNU_LENGTH = 19
LAND_NORMAL = "1"  # 일반 필지
LAND_MOUNTAIN = "2"  # 산(임야)


class PnuError(ValueError):
    """PNU 를 조립하거나 해석할 수 없을 때."""


@dataclass(frozen=True)
class ParsedPnu:
    pnu: str
    ld_code: str  # 법정동코드 10자리
    sido_code: str
    sgg_code: str  # 시군구코드 5자리 (시도2 + 시군구3) - 자치법규 조회에 사용
    emd_code: str
    ri_code: str
    mountain: bool
    main_no: int  # 본번
    sub_no: int  # 부번

    @property
    def jibun(self) -> str:
        """사람이 읽는 지번 표기. 예: '산 12-3', '100-5', '100'."""
        prefix = "산 " if self.mountain else ""
        if self.sub_no:
            return f"{prefix}{self.main_no}-{self.sub_no}"
        return f"{prefix}{self.main_no}"


def build_pnu(
    ld_code: str,
    main_no: int | str,
    sub_no: int | str = 0,
    *,
    mountain: bool = False,
) -> str:
    """법정동코드 + 지번으로 19자리 PNU 를 만든다.

    Args:
        ld_code: 법정동코드 10자리. 도로명주소 API 의 ``admCd`` 가 이 값이다.
        main_no: 본번.
        sub_no: 부번. 없으면 0.
        mountain: 산(임야) 여부. 도로명주소 API 의 ``mtYn`` 이 "1" 이면 True.

    Raises:
        PnuError: 코드나 지번이 규격을 벗어날 때.
    """
    code = str(ld_code).strip()
    if not re.fullmatch(r"\d{10}", code):
        raise PnuError(f"법정동코드는 숫자 10자리여야 합니다: {ld_code!r}")

    main = _to_int(main_no, "본번")
    sub = _to_int(sub_no, "부번")
    if not 0 <= main <= 9999:
        raise PnuError(f"본번은 0~9999 범위여야 합니다: {main}")
    if not 0 <= sub <= 9999:
        raise PnuError(f"부번은 0~9999 범위여야 합니다: {sub}")

    land_type = LAND_MOUNTAIN if mountain else LAND_NORMAL
    return f"{code}{land_type}{main:04d}{sub:04d}"


def parse_pnu(pnu: str) -> ParsedPnu:
    """19자리 PNU 를 구성요소로 분해한다."""
    code = str(pnu).strip()
    if not re.fullmatch(r"\d{19}", code):
        raise PnuError(f"PNU 는 숫자 19자리여야 합니다: {pnu!r}")

    land_type = code[10]
    if land_type not in (LAND_NORMAL, LAND_MOUNTAIN):
        raise PnuError(f"필지구분은 1(일반) 또는 2(산)여야 합니다: {land_type}")

    return ParsedPnu(
        pnu=code,
        ld_code=code[:10],
        sido_code=code[:2],
        sgg_code=code[:5],
        emd_code=code[5:8],
        ri_code=code[8:10],
        mountain=land_type == LAND_MOUNTAIN,
        main_no=int(code[11:15]),
        sub_no=int(code[15:19]),
    )


def _to_int(value: int | str, label: str) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text == "":
        return 0
    if not text.isdigit():
        raise PnuError(f"{label}은 숫자여야 합니다: {value!r}")
    return int(text)
