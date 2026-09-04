"""대지 규모 산정.

용도지역 법정 상한과 대지면적으로 건축 가능 규모의 '상한'을 계산한다.
조례로 강화된 값이나 완화 규정(용적률 인센티브 등)은 반영하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.zoning import ZoneLimit


@dataclass(frozen=True)
class SizeEstimate:
    """대지면적 기준 최대 건축 규모(법정 상한 기준)."""

    site_area_m2: float
    building_coverage_max_pct: float
    floor_area_ratio_max_pct: float
    max_building_area_m2: float  # 건축면적 상한 = 대지면적 x 건폐율
    max_total_floor_area_m2: float  # 연면적(용적률 산정용) 상한 = 대지면적 x 용적률
    approx_max_floors: float  # 참고용 층수 = 용적률 / 건폐율


def estimate_size(limit: ZoneLimit, site_area_m2: float) -> SizeEstimate | None:
    """법정 상한 기준 최대 건축 규모를 계산한다.

    Args:
        limit: 용도지역 법정 상한.
        site_area_m2: 대지면적(제곱미터). 0 이하이면 계산하지 않는다.

    Returns:
        SizeEstimate, 면적이 없거나 유효하지 않으면 None.
    """
    if not site_area_m2 or site_area_m2 <= 0:
        return None

    bcr = limit.building_coverage_max
    far = limit.floor_area_ratio_max
    return SizeEstimate(
        site_area_m2=round(site_area_m2, 2),
        building_coverage_max_pct=bcr,
        floor_area_ratio_max_pct=far,
        max_building_area_m2=round(site_area_m2 * bcr / 100, 2),
        max_total_floor_area_m2=round(site_area_m2 * far / 100, 2),
        approx_max_floors=round(far / bcr, 1) if bcr else 0.0,
    )
