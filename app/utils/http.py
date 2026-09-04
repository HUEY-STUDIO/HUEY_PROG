"""외부 공공 API 호출용 HTTP 헬퍼.

공공데이터포털 계열 API 는 장애/지연이 잦고, 오류를 HTTP 200 + 본문
에러코드로 돌려주는 경우가 많다. 여기서 재시도와 오류 정규화를 처리한다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class PublicApiError(RuntimeError):
    """외부 공공 API 호출 실패.

    Attributes:
        source: 어느 API 인지 (예: "juso", "vworld", "nsdi").
        detail: 사람이 읽을 수 있는 사유.
        status_code: 상류 HTTP 상태코드 (있는 경우).
    """

    def __init__(self, source: str, detail: str, status_code: int | None = None):
        self.source = source
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"[{source}] {detail}")


_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """프로세스 공용 AsyncClient. 커넥션 풀을 재사용한다."""
    global _client
    if _client is None or _client.is_closed:
        settings = get_settings()
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout,
            follow_redirects=True,
            headers={"User-Agent": "huey-prog-land-law/0.1"},
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def fetch(
    source: str,
    url: str,
    params: dict[str, Any],
    *,
    expect: str = "json",
) -> Any:
    """GET 요청 후 본문을 파싱해 돌려준다.

    Args:
        source: 오류 메시지에 붙일 API 식별자.
        url: 요청 URL.
        params: 쿼리 파라미터. None 값은 제거된다.
        expect: "json" 이면 dict/list 로, "text" 면 원문 문자열로 반환.

    Raises:
        PublicApiError: 재시도 후에도 실패했거나 응답을 파싱할 수 없을 때.
    """
    settings = get_settings()
    client = get_client()
    clean = {k: v for k, v in params.items() if v is not None}

    last_error: str = "unknown error"
    for attempt in range(settings.http_max_retries + 1):
        try:
            response = await client.get(url, params=clean)
        except httpx.TimeoutException:
            last_error = "요청 시간 초과"
        except httpx.HTTPError as exc:
            last_error = f"네트워크 오류: {exc}"
        else:
            if response.status_code >= 500:
                last_error = f"상류 서버 오류 (HTTP {response.status_code})"
            elif response.status_code >= 400:
                # 4xx 는 재시도해도 동일하므로 즉시 중단한다.
                raise PublicApiError(
                    source,
                    f"요청이 거부되었습니다 (HTTP {response.status_code}). "
                    "인증키와 요청 파라미터를 확인하세요.",
                    response.status_code,
                )
            else:
                return _parse(source, response, expect)

        if attempt < settings.http_max_retries:
            backoff = 0.5 * (2**attempt)
            logger.warning(
                "%s 호출 실패(%s), %.1f초 후 재시도 %d/%d",
                source,
                last_error,
                backoff,
                attempt + 1,
                settings.http_max_retries,
            )
            await asyncio.sleep(backoff)

    raise PublicApiError(source, last_error)


def _parse(source: str, response: httpx.Response, expect: str) -> Any:
    if expect == "text":
        return response.text
    try:
        return response.json()
    except ValueError:
        # 공공 API 는 인증키 오류 시 JSON 대신 XML/HTML 을 돌려주는 일이 흔하다.
        body = response.text.strip()
        snippet = body[:300].replace("\n", " ")
        raise PublicApiError(
            source,
            "JSON 응답을 기대했으나 다른 형식이 반환되었습니다. "
            f"인증키 등록 여부를 확인하세요. 응답 일부: {snippet}",
        ) from None
