"""3단계: 국가법령 조회 (건축법 / 국토계획법).

국가법령정보 공동활용(open.law.go.kr) DRF 를 사용한다.
  - 목록 조회 : {LAW_BASE_URL}/lawSearch.do?OC=..&target=law&type=JSON&query=..
  - 본문 조회 : {LAW_BASE_URL}/lawService.do?OC=..&target=law&type=JSON&ID=..&JO=..

응답 필드명이 한글이고 서비스별로 표기가 조금씩 달라, 고정 경로 대신
후보 키 목록으로 추출한다. 조문 본문 조회에 실패해도 조문 링크는 항상
제공하도록 설계했다(파이프라인이 법령 API 장애로 멈추지 않게).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.models import StatuteArticle
from app.utils import cache
from app.utils.http import PublicApiError, fetch

logger = logging.getLogger(__name__)

LAW_VIEW_URL = "https://www.law.go.kr/법령/{name}/제{article}조"


@dataclass(frozen=True)
class ArticleRef:
    """조회할 조문 지정."""

    law_name: str
    article_no: int
    title: str

    @property
    def jo_param(self) -> str:
        """DRF 의 JO 파라미터 형식(조 4자리 + 항 2자리)."""
        return f"{self.article_no:04d}00"

    @property
    def link(self) -> str:
        return LAW_VIEW_URL.format(name=self.law_name, article=self.article_no)


# 건폐율/용적률의 근거가 되는 핵심 조문.
CORE_ARTICLES: tuple[ArticleRef, ...] = (
    ArticleRef("건축법", 55, "건축물의 건폐율"),
    ArticleRef("건축법", 56, "건축물의 용적률"),
    ArticleRef("국토의 계획 및 이용에 관한 법률", 77, "용도지역의 건폐율"),
    ArticleRef("국토의 계획 및 이용에 관한 법률", 78, "용도지역에서의 용적률"),
    ArticleRef("국토의 계획 및 이용에 관한 법률 시행령", 84, "용도지역안에서의 건폐율"),
    ArticleRef("국토의 계획 및 이용에 관한 법률 시행령", 85, "용도지역 안에서의 용적률"),
)


def _collect_text(node: Any, out: list[str]) -> None:
    """중첩된 조문 구조에서 문자열만 모아 평문으로 만든다."""
    if isinstance(node, str):
        text = re.sub(r"<[^>]+>", "", node).strip()
        if text:
            out.append(text)
    elif isinstance(node, dict):
        for value in node.values():
            _collect_text(value, out)
    elif isinstance(node, list):
        for value in node:
            _collect_text(value, out)


async def search_laws(query: str, *, display: int = 10) -> list[dict[str, Any]]:
    """법령 목록 조회. 원본 레코드를 그대로 반환한다."""
    settings = get_settings()
    if not settings.law_oc:
        raise PublicApiError("law", "LAW_OC 가 설정되지 않았습니다. .env 를 확인하세요.")

    async def _call() -> Any:
        return await fetch(
            "law",
            f"{settings.law_base_url}/lawSearch.do",
            {
                "OC": settings.law_oc,
                "target": "law",
                "type": "JSON",
                "query": query,
                "display": display,
                "page": 1,
            },
        )

    payload = await cache.get_or_set(f"law-search:{query}:{display}", _call)
    raise_if_auth_error(payload)
    return extract_drf_records(payload)


def raise_if_auth_error(payload: Any) -> None:
    """DRF 가 HTTP 200 으로 돌려주는 인증 실패 응답을 예외로 바꾼다.

    국가법령정보는 OC 가 틀리거나 호출 서버 IP 가 등록되지 않은 경우에도
    HTTP 200 에 아래와 같은 본문을 실어 보낸다. 그대로 두면 '결과 0건' 으로
    보여 원인을 알 수 없다.

        {"result": "사용자 정보 검증에 실패하였습니다.",
         "msg": "OPEN API 호출 시 사용자 검증을 위하여 정확한 서버장비의
                 IP주소 및 도메인주소를 등록해 주세요."}
    """
    if not isinstance(payload, dict):
        return
    result = payload.get("result")
    if isinstance(result, str) and "실패" in result:
        msg = payload.get("msg") or ""
        raise PublicApiError("law", f"{result} {msg}".strip())


def extract_drf_records(payload: Any) -> list[dict[str, Any]]:
    """DRF 응답에서 레코드 배열을 찾는다.

    응답 형태가 ``{"LawSearch": {..., "law": [...]}}`` /
    ``{"OrdinSearch": {..., "law": [...]}}`` 처럼 최상위 래퍼 이름이 다르고,
    결과가 1건이면 리스트 대신 dict 로 오는 경우가 있어 둘 다 처리한다.
    """
    if not isinstance(payload, dict):
        return []

    for wrapper in payload.values():
        if not isinstance(wrapper, dict):
            continue
        for value in wrapper.values():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                return value
        # 단건 응답: 리스트 대신 dict 하나가 들어온다.
        for value in wrapper.values():
            if isinstance(value, dict):
                return [value]
    return []


async def fetch_article(ref: ArticleRef) -> StatuteArticle:
    """조문 본문을 가져온다. 실패하면 링크만 담은 결과를 돌려준다."""
    settings = get_settings()
    fallback = StatuteArticle(
        law_name=ref.law_name,
        article_no=f"제{ref.article_no}조",
        article_title=ref.title,
        link=ref.link,
    )
    if not settings.law_oc:
        return fallback

    async def _call() -> Any:
        return await fetch(
            "law",
            f"{settings.law_base_url}/lawService.do",
            {
                "OC": settings.law_oc,
                "target": "law",
                "type": "JSON",
                "LM": ref.law_name,
                "JO": ref.jo_param,
            },
        )

    try:
        payload = await cache.get_or_set(f"law-article:{ref.law_name}:{ref.jo_param}", _call)
    except PublicApiError as exc:
        logger.warning("조문 조회 실패(%s 제%d조): %s", ref.law_name, ref.article_no, exc.detail)
        return fallback

    try:
        raise_if_auth_error(payload)
    except PublicApiError as exc:
        logger.warning("조문 조회 인증 실패(%s 제%d조): %s", ref.law_name, ref.article_no, exc.detail)
        return fallback

    chunks: list[str] = []
    _collect_text(payload, chunks)
    if not chunks:
        return fallback

    content = "\n".join(chunks)
    # 응답 전체를 그대로 담으면 지나치게 길어지므로 앞부분만 발췌한다.
    if len(content) > 4000:
        content = content[:4000] + "\n... (이하 생략, 링크에서 전문 확인)"

    return StatuteArticle(
        law_name=ref.law_name,
        article_no=f"제{ref.article_no}조",
        article_title=ref.title,
        content=content,
        link=ref.link,
    )


async def core_statutes(*, with_content: bool = False) -> list[StatuteArticle]:
    """건폐율/용적률 근거 조문 목록.

    Args:
        with_content: True 면 본문까지 조회한다(호출 6건 추가). 기본은 링크만.
    """
    if not with_content:
        return [
            StatuteArticle(
                law_name=ref.law_name,
                article_no=f"제{ref.article_no}조",
                article_title=ref.title,
                link=ref.link,
            )
            for ref in CORE_ARTICLES
        ]
    return [await fetch_article(ref) for ref in CORE_ARTICLES]
