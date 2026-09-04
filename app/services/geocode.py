"""1단계: 주소 -> 지번(PNU) / 좌표 변환.

  - 도로명주소 API(business.juso.go.kr) : 주소 검색 -> 법정동코드/본번/부번/산여부
      PNU 조립에 필요한 값을 모두 돌려주므로 지번 변환의 기준으로 삼는다.
  - 브이월드 Geocoder API 2.0 : 주소 -> 경위도
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.domain.pnu import build_pnu
from app.models import AddressCandidate, Coordinate
from app.utils import cache
from app.utils.http import PublicApiError, fetch

logger = logging.getLogger(__name__)


async def search_addresses(keyword: str, limit: int = 10) -> list[AddressCandidate]:
    """도로명주소 API 로 주소를 검색해 PNU 까지 붙여 돌려준다.

    Args:
        keyword: 검색어. 도로명주소/지번주소/건물명 모두 가능.
        limit: 최대 결과 수 (1~100).

    Raises:
        PublicApiError: 인증키 미설정 또는 상류 오류.
    """
    settings = get_settings()
    if not settings.juso_api_key:
        raise PublicApiError("juso", "JUSO_API_KEY 가 설정되지 않았습니다. .env 를 확인하세요.")

    keyword = keyword.strip()
    if not keyword:
        return []

    count = max(1, min(limit, 100))
    cache_key = f"juso:{count}:{keyword}"

    async def _call() -> dict:
        return await fetch(
            "juso",
            settings.juso_base_url,
            {
                "confmKey": settings.juso_api_key,
                "currentPage": 1,
                "countPerPage": count,
                "keyword": keyword,
                "resultType": "json",
            },
        )

    payload = await cache.get_or_set(cache_key, _call)
    results = (payload or {}).get("results") or {}
    common = results.get("common") or {}

    error_code = common.get("errorCode")
    if error_code and error_code != "0":
        raise PublicApiError(
            "juso", f"{common.get('errorMessage', '주소 검색 실패')} (code={error_code})"
        )

    candidates: list[AddressCandidate] = []
    for item in results.get("juso") or []:
        candidate = _to_candidate(item)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _to_candidate(item: dict) -> AddressCandidate | None:
    """도로명주소 API 결과 1건을 AddressCandidate 로 변환.

    PNU 조립에 필요한 값이 빠져 있으면 (일부 특수 주소) None 을 돌려주고 건너뛴다.
    """
    ld_code = (item.get("admCd") or "").strip()
    main_no = (item.get("lnbrMnnm") or "").strip()
    if not ld_code or not main_no:
        logger.warning("PNU 조립 불가한 주소 건너뜀: %s", item.get("roadAddr"))
        return None

    mountain = str(item.get("mtYn") or "0").strip() == "1"
    sub_no = (item.get("lnbrSlno") or "0").strip() or "0"

    try:
        pnu = build_pnu(ld_code, main_no, sub_no, mountain=mountain)
    except ValueError as exc:
        logger.warning("PNU 조립 실패(%s): %s", exc, item.get("roadAddr"))
        return None

    return AddressCandidate(
        road_address=item.get("roadAddr") or "",
        jibun_address=item.get("jibunAddr") or "",
        zip_code=item.get("zipNo") or None,
        sido=item.get("siNm") or None,
        sigungu=item.get("sggNm") or None,
        eupmyeondong=item.get("emdNm") or None,
        ld_code=ld_code,
        mountain=mountain,
        main_no=int(main_no),
        sub_no=int(sub_no),
        pnu=pnu,
    )


async def geocode(address: str, *, address_type: str = "road") -> Coordinate | None:
    """브이월드 Geocoder 2.0 으로 주소를 경위도로 변환한다.

    Args:
        address: 변환할 주소.
        address_type: "road"(도로명) 또는 "parcel"(지번).

    Returns:
        좌표. 브이월드가 매칭에 실패하면 None. 지오코더는 일 호출 제한이 있어
        실패를 예외로 올리지 않고 None 으로 처리해 파이프라인 전체를 막지 않는다.
    """
    settings = get_settings()
    if not settings.vworld_api_key:
        logger.info("VWORLD_API_KEY 미설정 - 좌표 변환을 건너뜁니다.")
        return None

    cache_key = f"vworld:{address_type}:{address}"

    async def _call() -> dict:
        return await fetch(
            "vworld",
            settings.vworld_base_url,
            {
                "service": "address",
                "request": "getcoord",
                "version": "2.0",
                "crs": "epsg:4326",
                "type": address_type,
                "address": address,
                "refine": "true",
                "simple": "false",
                "format": "json",
                "key": settings.vworld_api_key,
            },
        )

    try:
        payload = await cache.get_or_set(cache_key, _call)
    except PublicApiError as exc:
        logger.warning("좌표 변환 실패: %s", exc)
        return None

    response = (payload or {}).get("response") or {}
    if response.get("status") != "OK":
        logger.info(
            "브이월드 좌표 미매칭 (status=%s, address=%s)", response.get("status"), address
        )
        return None

    point = ((response.get("result") or {}).get("point")) or {}
    try:
        return Coordinate(longitude=float(point["x"]), latitude=float(point["y"]))
    except (KeyError, TypeError, ValueError):
        logger.warning("브이월드 좌표 파싱 실패: %s", point)
        return None
