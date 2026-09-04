"""2단계: 지번(PNU) -> 대지개요 (용도지역 / 지목 / 면적).

국가공간정보포털(NSDI) 오픈API 두 가지를 조합한다.
  - 토지이용계획속성   : 해당 필지에 걸린 지역·지구 목록 (용도지역 포함)
  - 토지특성정보       : 지목, 공부상 면적, 개별공시지가

주의: 공공데이터포털 계열 API 는 응답 래퍼 키 이름이 서비스/버전마다 다르다
      (``landUses.field``, ``response.body.items.item`` 등). 여기서는 특정
      키에 의존하지 않고 JSON 을 훑어 레코드 배열을 찾는 방식으로 파싱한다.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.domain.pnu import parse_pnu
from app.domain.zoning import lookup_limit, normalize_zone_name
from app.models import SiteOverview, ZoneDesignation
from app.utils import cache
from app.utils.http import PublicApiError, fetch
from app.utils.parsing import pick_field, to_float, to_int

logger = logging.getLogger(__name__)

# 대표 용도지역을 고를 때의 우선순위. 저촉(일부만 걸침)보다 저촉이 아닌 것을,
# 그 중에서도 건폐율/용적률이 실제로 결정되는 국토계획법상 용도지역을 우선한다.
_NON_CONFLICT_FLAGS = {"0", "n", "no", "false", ""}


async def fetch_land_use_attrs(pnu: str) -> list[dict[str, Any]]:
    """토지이용계획속성 조회. 필지에 걸린 지역·지구 레코드 목록을 반환."""
    return await _fetch_nsdi(
        "nsdi-landuse",
        "/LandUseService/attr/getLandUseAttr",
        pnu,
    )


async def fetch_land_characteristics(pnu: str) -> list[dict[str, Any]]:
    """토지특성정보 조회. 지목/면적/공시지가 레코드 목록을 반환."""
    return await _fetch_nsdi(
        "nsdi-landchar",
        "/LandCharacteristicsService/attr/getLandCharacteristics",
        pnu,
    )


async def _fetch_nsdi(source: str, path: str, pnu: str) -> list[dict[str, Any]]:
    settings = get_settings()
    if not settings.data_go_kr_service_key:
        raise PublicApiError(
            source, "DATA_GO_KR_SERVICE_KEY 가 설정되지 않았습니다. .env 를 확인하세요."
        )

    url = f"{settings.nsdi_base_url}{path}"

    async def _call() -> Any:
        return await fetch(
            source,
            url,
            {
                "serviceKey": settings.data_go_kr_service_key,
                "pnu": pnu,
                "format": "json",
                "numOfRows": 100,
                "pageNo": 1,
            },
        )

    payload = await cache.get_or_set(f"{source}:{pnu}", _call)
    return extract_records(payload)


def extract_records(payload: Any) -> list[dict[str, Any]]:
    """공공 API 응답에서 레코드 배열을 찾아낸다.

    서비스마다 래퍼가 달라(``{"landUses": {"field": [...]}}``,
    ``{"response": {"body": {"items": {"item": [...]}}}}`` 등) 고정 경로로
    파싱하면 쉽게 깨진다. dict 를 재귀적으로 훑어 '딕셔너리들의 리스트' 중
    가장 큰 것을 레코드 배열로 본다.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    best: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        nonlocal best
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            records = [x for x in node if isinstance(x, dict)]
            if len(records) == len(node) and len(records) > len(best):
                best = records
            for value in node:
                walk(value)

    walk(payload)

    # 레코드가 딱 하나일 때 리스트가 아닌 dict 로 오는 서비스가 있다.
    if not best:
        for key in ("item", "field", "row"):
            node = _find_key(payload, key)
            if isinstance(node, dict):
                return [node]
    return best


def _find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def build_designations(records: list[dict[str, Any]]) -> list[ZoneDesignation]:
    """토지이용계획속성 레코드를 ZoneDesignation 목록으로 변환."""
    designations: list[ZoneDesignation] = []
    seen: set[tuple[str, str | None]] = set()

    for record in records:
        name = pick_field(
            record,
            "prposAreaDstrcCodeNm",
            "prposAreaDstrcNm",
            "lawgTgtNm",
            "dgmNm",
            "name",
        )
        if not name:
            continue
        name = str(name).strip()
        code = pick_field(record, "prposAreaDstrcCode", "prposAreaDstrcCd", "code")
        code = str(code).strip() if code else None

        if (name, code) in seen:
            continue
        seen.add((name, code))

        conflict_raw = pick_field(record, "cnflcAt", "cnflcYn")
        conflict: bool | None = None
        if conflict_raw is not None:
            conflict = str(conflict_raw).strip().lower() not in _NON_CONFLICT_FLAGS

        designations.append(
            ZoneDesignation(
                name=name,
                code=code,
                conflict=conflict,
                registered_at=pick_field(record, "registDt", "lastUpdtDt"),
                is_use_district=normalize_zone_name(name) is not None,
            )
        )
    return designations


def pick_primary_zone(designations: list[ZoneDesignation]) -> str | None:
    """건폐율/용적률을 결정할 대표 용도지역을 고른다.

    한 필지에 여러 용도지역이 걸칠 수 있다(예: 일부 자연녹지 + 일부 1종일반주거).
    저촉이 아닌(필지 전체에 적용되는) 용도지역을 우선하고, 그것도 여러 개면
    건폐율 상한이 가장 높은 것을 대표로 삼되 warnings 로 알린다.
    """
    zones = [d for d in designations if d.is_use_district]
    if not zones:
        return None

    non_conflict = [d for d in zones if d.conflict is not True]
    pool = non_conflict or zones
    if len(pool) == 1:
        return pool[0].name

    def sort_key(d: ZoneDesignation) -> float:
        limit = lookup_limit(d.name)
        return limit.building_coverage_max if limit else -1.0

    return max(pool, key=sort_key).name


async def build_overview(pnu: str) -> SiteOverview:
    """PNU 하나에 대한 대지개요를 조립한다.

    두 API 중 하나가 실패해도 나머지 정보로 결과를 만들고, 실패 사유는
    ``warnings`` 에 담아 호출자가 판단할 수 있게 한다.
    """
    parsed = parse_pnu(pnu)
    warnings: list[str] = []

    designations: list[ZoneDesignation] = []
    try:
        designations = build_designations(await fetch_land_use_attrs(pnu))
    except PublicApiError as exc:
        warnings.append(f"토지이용계획 조회 실패: {exc.detail}")

    land_category: str | None = None
    area_m2: float | None = None
    official_price: int | None = None
    try:
        char_records = await fetch_land_characteristics(pnu)
    except PublicApiError as exc:
        warnings.append(f"토지특성 조회 실패: {exc.detail}")
    else:
        if char_records:
            latest = char_records[0]
            land_category = pick_field(latest, "lndcgrCodeNm", "lndcgrNm", "jimok")
            area_m2 = to_float(pick_field(latest, "lndpclAr", "area", "ar"))
            official_price = to_int(pick_field(latest, "pblntfPclnd", "pblntfPclndSe"))
            # 토지특성에도 용도지역이 실려 있어, 토지이용계획이 비었을 때 보완한다.
            if not designations:
                for key in ("prposArea1Nm", "prposArea2Nm"):
                    name = pick_field(latest, key)
                    if name:
                        designations.append(
                            ZoneDesignation(
                                name=str(name).strip(),
                                is_use_district=normalize_zone_name(str(name)) is not None,
                            )
                        )
        else:
            warnings.append("토지특성 정보가 조회되지 않았습니다 (지목/면적 미확인).")

    primary = pick_primary_zone(designations)
    normalized_name = None
    if primary:
        limit = lookup_limit(primary)
        normalized_name = limit.name if limit else None

    use_zones = [d for d in designations if d.is_use_district]
    if len(use_zones) > 1:
        names = ", ".join(d.name for d in use_zones)
        warnings.append(
            f"용도지역이 둘 이상 확인되었습니다({names}). 둘 이상 걸친 대지는 "
            "국토계획법 제84조에 따라 면적 안분 등 별도 검토가 필요합니다."
        )
    if primary and normalized_name is None:
        warnings.append(f"용도지역 '{primary}' 를 표준 명칭으로 정규화하지 못했습니다.")

    return SiteOverview(
        pnu=pnu,
        jibun=parsed.jibun,
        land_category=str(land_category) if land_category else None,
        area_m2=area_m2,
        official_price_krw=official_price,
        primary_zone=primary,
        primary_zone_normalized=normalized_name,
        designations=designations,
        warnings=warnings,
    )
