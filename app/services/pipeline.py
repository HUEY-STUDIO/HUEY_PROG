"""전체 파이프라인 조립: 주소 -> 대지개요 -> 법정 상한 -> 조례 후보."""

from __future__ import annotations

import logging

from app.domain.calc import estimate_size
from app.domain.pnu import parse_pnu
from app.domain.zoning import lookup_limit
from app.models import (
    AddressCandidate,
    LegalLimit,
    SiteReport,
    SizeEstimateOut,
)
from app.services import geocode, land_use, law, ordinance
from app.utils.http import PublicApiError

logger = logging.getLogger(__name__)

EUM_URL = "https://www.eum.go.kr/web/ar/lu/luLandDet.jsp"
VWORLD_MAP_URL = "https://map.vworld.kr/map/maps.do"


class AddressNotFound(LookupError):
    """검색 결과가 없거나 요청한 후보 번호가 범위를 벗어남."""


async def analyze_address(
    query: str,
    *,
    candidate_index: int = 0,
    with_statute_content: bool = False,
    include_ordinances: bool = True,
) -> SiteReport:
    """주소 문자열 하나로 종합 결과를 만든다.

    Args:
        query: 주소 검색어.
        candidate_index: 검색 결과가 여러 건일 때 사용할 후보 번호(0-base).
        with_statute_content: True 면 국가법령 조문 본문까지 조회한다.
        include_ordinances: False 면 조례 검색을 건너뛴다(호출 절약용).

    Raises:
        AddressNotFound: 주소를 찾지 못했을 때.
        PublicApiError: 주소 검색 자체가 실패했을 때.
    """
    candidates = await geocode.search_addresses(query, limit=max(10, candidate_index + 1))
    if not candidates:
        raise AddressNotFound(f"'{query}' 에 해당하는 주소를 찾지 못했습니다.")
    if candidate_index >= len(candidates):
        raise AddressNotFound(
            f"후보 번호 {candidate_index} 가 범위를 벗어났습니다 (검색된 후보 {len(candidates)}건)."
        )

    address = candidates[candidate_index]
    warnings: list[str] = []
    if len(candidates) > 1 and candidate_index == 0:
        warnings.append(
            f"주소 후보가 {len(candidates)}건 검색되어 첫 번째를 사용했습니다. "
            "다른 필지라면 candidate_index 로 지정하세요."
        )

    return await _build_report(
        query=query,
        address=address,
        warnings=warnings,
        with_statute_content=with_statute_content,
        include_ordinances=include_ordinances,
    )


async def analyze_pnu(
    pnu: str,
    *,
    with_statute_content: bool = False,
    include_ordinances: bool = True,
) -> SiteReport:
    """PNU 를 이미 알고 있을 때 주소 검색을 건너뛰고 조회한다.

    지자체명을 알 수 없으므로 조례 검색은 생략된다.
    """
    parsed = parse_pnu(pnu)
    address = AddressCandidate(
        road_address="",
        jibun_address="",
        ld_code=parsed.ld_code,
        mountain=parsed.mountain,
        main_no=parsed.main_no,
        sub_no=parsed.sub_no,
        pnu=parsed.pnu,
    )
    return await _build_report(
        query=pnu,
        address=address,
        warnings=["PNU 직접 조회이므로 지자체명이 없어 조례 검색을 생략했습니다."]
        if include_ordinances
        else [],
        with_statute_content=with_statute_content,
        include_ordinances=False,
        skip_geocode=True,
    )


async def _build_report(
    *,
    query: str,
    address: AddressCandidate,
    warnings: list[str],
    with_statute_content: bool,
    include_ordinances: bool,
    skip_geocode: bool = False,
) -> SiteReport:
    coordinate = None
    if not skip_geocode:
        coordinate = await geocode.geocode(address.road_address or query, address_type="road")
        if coordinate is None and address.jibun_address:
            coordinate = await geocode.geocode(address.jibun_address, address_type="parcel")
        if coordinate is None:
            warnings.append("좌표 변환에 실패했습니다 (브이월드 키 미설정 또는 미매칭).")

    overview = await land_use.build_overview(address.pnu)
    warnings.extend(overview.warnings)

    legal_limit: LegalLimit | None = None
    size_estimate: SizeEstimateOut | None = None

    limit = lookup_limit(overview.primary_zone) if overview.primary_zone else None
    if limit is not None:
        legal_limit = LegalLimit(
            zone_name=limit.name,
            zone_category=limit.category.value,
            building_coverage_max_pct=limit.building_coverage_max,
            floor_area_ratio_min_pct=limit.floor_area_ratio_min,
            floor_area_ratio_max_pct=limit.floor_area_ratio_max,
            statute_refs=list(limit.statute_refs),
        )
        estimate = estimate_size(limit, overview.area_m2 or 0)
        if estimate is not None:
            size_estimate = SizeEstimateOut(
                site_area_m2=estimate.site_area_m2,
                max_building_area_m2=estimate.max_building_area_m2,
                max_total_floor_area_m2=estimate.max_total_floor_area_m2,
                approx_max_floors=estimate.approx_max_floors,
            )
        else:
            warnings.append("대지면적을 확인하지 못해 규모 산정을 건너뛰었습니다.")
    elif overview.primary_zone:
        warnings.append(
            f"용도지역 '{overview.primary_zone}' 에 대한 법정 상한 표를 찾지 못했습니다."
        )
    else:
        warnings.append("용도지역을 확인하지 못해 건폐율/용적률을 산정할 수 없습니다.")

    try:
        statutes = await law.core_statutes(with_content=with_statute_content)
    except PublicApiError as exc:
        warnings.append(f"국가법령 조회 실패: {exc.detail}")
        statutes = []

    ordinance_hits = []
    if include_ordinances:
        ordinance_hits, ordinance_warnings = await ordinance.find_for_site(
            address.sido, address.sigungu
        )
        warnings.extend(ordinance_warnings)

    references = {
        "토지이음": f"{EUM_URL}?pnu={address.pnu}",
        "국가법령정보센터": "https://www.law.go.kr/",
    }
    if coordinate is not None:
        references["브이월드 지도"] = (
            f"{VWORLD_MAP_URL}?x={coordinate.longitude}&y={coordinate.latitude}"
        )

    return SiteReport(
        query=query,
        address=address,
        coordinate=coordinate,
        overview=overview,
        legal_limit=legal_limit,
        size_estimate=size_estimate,
        statutes=statutes,
        ordinance_candidates=ordinance_hits,
        references=references,
        warnings=_dedupe(warnings),
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
