"""조회 API 라우터."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.domain.calc import estimate_size
from app.domain.pnu import PnuError
from app.domain.zoning import all_limits, lookup_limit
from app.models import (
    AddressCandidate,
    LegalLimit,
    OrdinanceHit,
    SiteReport,
    SizeEstimateOut,
)
from app.services import geocode, ordinance, pipeline
from app.utils.http import PublicApiError

router = APIRouter(prefix="/api/v1", tags=["lookup"])


def _to_http_error(exc: PublicApiError) -> HTTPException:
    """상류 API 오류를 적절한 HTTP 상태로 변환한다."""
    if "설정되지 않" in exc.detail:
        # 서버 설정 문제이므로 클라이언트 재시도로 해결되지 않는다.
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


@router.get(
    "/address/search",
    response_model=list[AddressCandidate],
    summary="주소 검색 (1단계: 주소 -> 지번/PNU)",
)
async def search_address(
    q: str = Query(description="도로명주소·지번주소·건물명 등 검색어", min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[AddressCandidate]:
    try:
        return await geocode.search_addresses(q, limit=limit)
    except PublicApiError as exc:
        raise _to_http_error(exc) from exc


@router.get(
    "/site",
    response_model=SiteReport,
    summary="주소 종합 조회 (대지개요 + 법정 상한 + 조례 후보)",
)
async def get_site(
    address: str = Query(description="조회할 주소", min_length=1),
    candidate_index: int = Query(
        default=0, ge=0, description="주소 후보가 여러 건일 때 사용할 번호(0-base)"
    ),
    with_statute_content: bool = Query(
        default=False, description="국가법령 조문 본문까지 조회할지 여부"
    ),
    include_ordinances: bool = Query(default=True, description="조례 후보 검색 포함 여부"),
) -> SiteReport:
    try:
        return await pipeline.analyze_address(
            address,
            candidate_index=candidate_index,
            with_statute_content=with_statute_content,
            include_ordinances=include_ordinances,
        )
    except pipeline.AddressNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PublicApiError as exc:
        raise _to_http_error(exc) from exc


@router.get(
    "/site/pnu/{pnu}",
    response_model=SiteReport,
    summary="PNU 직접 조회",
)
async def get_site_by_pnu(
    pnu: str,
    with_statute_content: bool = Query(default=False),
) -> SiteReport:
    try:
        return await pipeline.analyze_pnu(pnu, with_statute_content=with_statute_content)
    except PnuError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PublicApiError as exc:
        raise _to_http_error(exc) from exc


@router.get(
    "/limits",
    response_model=list[LegalLimit],
    summary="용도지역별 법정 건폐율/용적률 상한 전체 표",
)
async def list_limits() -> list[LegalLimit]:
    return [
        LegalLimit(
            zone_name=limit.name,
            zone_category=limit.category.value,
            building_coverage_max_pct=limit.building_coverage_max,
            floor_area_ratio_min_pct=limit.floor_area_ratio_min,
            floor_area_ratio_max_pct=limit.floor_area_ratio_max,
            statute_refs=list(limit.statute_refs),
        )
        for limit in all_limits()
    ]


@router.get(
    "/limits/estimate",
    response_model=SizeEstimateOut,
    summary="용도지역 + 대지면적으로 최대 건축 규모 산정",
)
async def estimate(
    zone: str = Query(description="용도지역 명칭 (예: 제2종일반주거지역)"),
    area_m2: float = Query(gt=0, description="대지면적(제곱미터)"),
) -> SizeEstimateOut:
    limit = lookup_limit(zone)
    if limit is None:
        raise HTTPException(
            status_code=422, detail=f"용도지역 '{zone}' 을(를) 인식하지 못했습니다."
        )
    result = estimate_size(limit, area_m2)
    if result is None:
        raise HTTPException(status_code=422, detail="대지면적이 유효하지 않습니다.")
    return SizeEstimateOut(
        site_area_m2=result.site_area_m2,
        max_building_area_m2=result.max_building_area_m2,
        max_total_floor_area_m2=result.max_total_floor_area_m2,
        approx_max_floors=result.approx_max_floors,
    )


@router.get(
    "/ordinances",
    response_model=list[OrdinanceHit],
    summary="지자체 조례 후보 검색 (자동 판정 아님)",
)
async def search_ordinance(
    sido: str | None = Query(default=None, description="시도명 (예: 서울특별시)"),
    sigungu: str | None = Query(default=None, description="시군구명 (예: 강남구)"),
) -> list[OrdinanceHit]:
    if not sido and not sigungu:
        raise HTTPException(status_code=422, detail="sido 또는 sigungu 중 하나는 필요합니다.")
    hits, _ = await ordinance.find_for_site(sido, sigungu)
    return hits
