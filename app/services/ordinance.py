"""4단계: 지자체 조례(자치법규) 후보 검색.

프로젝트 기획서의 판단대로, 조례는 지자체마다 조문 구조·표현이 제각각이라
"이 대지에 이 조항이 적용된다"를 완전 자동 판정하는 것은 1차 목표가 아니다.
이 모듈은 **후보를 찾아 링크로 제시**하는 데까지만 책임진다.

검색 전략:
  대지가 속한 시군구명 + 건축 규모를 좌우하는 핵심 조례명으로 질의를 만들고,
  자치법규 목록 조회 API 결과를 지자체명으로 한 번 더 걸러낸다.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.models import OrdinanceHit
from app.services.law import extract_drf_records, raise_if_auth_error
from app.utils import cache
from app.utils.http import PublicApiError, fetch
from app.utils.parsing import pick_field

logger = logging.getLogger(__name__)

LAW_HOST = "https://www.law.go.kr"

# 건폐율/용적률 등 대지 규모를 실제로 결정하는 조례들.
CORE_ORDINANCE_KINDS: tuple[str, ...] = ("도시계획조례", "건축조례")


async def search_ordinances(query: str, *, display: int = 20) -> list[OrdinanceHit]:
    """자치법규 목록 조회 API 로 조례를 검색한다."""
    settings = get_settings()
    if not settings.law_oc:
        raise PublicApiError("ordin", "LAW_OC 가 설정되지 않았습니다. .env 를 확인하세요.")

    async def _call() -> Any:
        return await fetch(
            "ordin",
            f"{settings.law_base_url}/lawSearch.do",
            {
                "OC": settings.law_oc,
                "target": "ordin",
                "type": "JSON",
                "query": query,
                "display": display,
                "page": 1,
            },
        )

    payload = await cache.get_or_set(f"ordin-search:{query}:{display}", _call)
    raise_if_auth_error(payload)
    return [hit for hit in (_to_hit(r) for r in extract_drf_records(payload)) if hit is not None]


def _to_hit(record: dict[str, Any]) -> OrdinanceHit | None:
    title = pick_field(record, "자치법규명", "법령명한글", "자치법규명한글")
    if not title:
        return None

    link = pick_field(record, "자치법규상세링크", "법령상세링크")
    if link and str(link).startswith("/"):
        link = LAW_HOST + str(link)

    return OrdinanceHit(
        title=str(title).strip(),
        local_gov=pick_field(record, "지자체기관명", "소관부처명"),
        ordinance_id=pick_field(record, "자치법규ID", "자치법규일련번호", "법령ID"),
        promulgation_date=pick_field(record, "공포일자"),
        link=str(link) if link else None,
    )


async def find_for_site(
    sido: str | None,
    sigungu: str | None,
    *,
    extra_terms: tuple[str, ...] = (),
) -> tuple[list[OrdinanceHit], list[str]]:
    """대지가 속한 지자체의 핵심 조례 후보를 모은다.

    Args:
        sido: 시도명 (예: "서울특별시").
        sigungu: 시군구명 (예: "강남구"). 광역시의 자치구 조례는 구 단위,
            도시계획조례는 시 단위인 경우가 섞여 있어 두 단위 모두 검색한다.
        extra_terms: 추가로 검색할 조례명 키워드.

    Returns:
        (후보 목록, 경고 메시지 목록). 인증키 미설정 등으로 검색이 불가능해도
        예외를 올리지 않고 경고로 돌려준다.
    """
    warnings: list[str] = []
    if not sido and not sigungu:
        return [], ["지자체를 특정할 수 없어 조례를 검색하지 못했습니다."]

    # 시군구가 있으면 시군구 우선, 없으면 시도 단위로 검색한다.
    regions = [r for r in (sigungu, sido) if r]
    kinds = CORE_ORDINANCE_KINDS + extra_terms

    hits: list[OrdinanceHit] = []
    seen: set[str] = set()
    for region in regions:
        for kind in kinds:
            try:
                results = await search_ordinances(f"{region} {kind}")
            except PublicApiError as exc:
                warnings.append(f"조례 검색 실패({region} {kind}): {exc.detail}")
                continue

            for hit in results:
                # 질의어가 느슨해 다른 지자체 조례가 섞여 들어올 수 있다.
                haystack = f"{hit.title} {hit.local_gov or ''}"
                if region not in haystack:
                    continue
                key = hit.ordinance_id or hit.title
                if key in seen:
                    continue
                seen.add(key)
                hits.append(hit)

    if not hits and not warnings:
        warnings.append(
            "해당 지자체의 조례 후보를 찾지 못했습니다. "
            "국가법령정보센터에서 직접 검색해 확인하세요."
        )
    return hits, warnings
