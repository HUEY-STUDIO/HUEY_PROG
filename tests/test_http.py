import httpx
import pytest
import respx

from app.config import get_settings
from app.utils import cache
from app.utils.http import PublicApiError, close_client, fetch


@pytest.fixture(autouse=True)
async def _close_http_client():
    yield
    await close_client()


@pytest.fixture
def fast_retries(monkeypatch):
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")
    monkeypatch.setenv("HTTP_TIMEOUT", "1.0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_fetch_retries_server_errors_then_succeeds(fast_retries):
    route = respx.get("https://example.test/api").mock(
        side_effect=[
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    result = await fetch("test", "https://example.test/api", {"a": 1})

    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_fetch_gives_up_after_max_retries(fast_retries):
    route = respx.get("https://example.test/api").mock(
        return_value=httpx.Response(500, text="boom")
    )

    with pytest.raises(PublicApiError):
        await fetch("test", "https://example.test/api", {})

    assert route.call_count == 3  # 최초 1회 + 재시도 2회


@respx.mock
async def test_fetch_does_not_retry_client_errors(fast_retries):
    route = respx.get("https://example.test/api").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert route.call_count == 1
    assert exc.value.status_code == 401


@respx.mock
async def test_fetch_reports_non_json_response_clearly():
    # 공공 API 는 인증키 오류 시 JSON 대신 XML 을 돌려주는 일이 흔하다.
    respx.get("https://example.test/api").mock(
        return_value=httpx.Response(
            200,
            text="<OpenAPI_ServiceResponse><errMsg>SERVICE KEY IS NOT REGISTERED ERROR"
            "</errMsg></OpenAPI_ServiceResponse>",
        )
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert "인증키" in exc.value.detail
    assert "SERVICE KEY IS NOT REGISTERED" in exc.value.detail


@respx.mock
async def test_fetch_drops_none_params():
    route = respx.get("https://example.test/api").mock(
        return_value=httpx.Response(200, json={})
    )

    await fetch("test", "https://example.test/api", {"a": 1, "b": None})

    assert "b" not in route.calls[0].request.url.params
    assert route.calls[0].request.url.params["a"] == "1"


@respx.mock
async def test_cache_prevents_duplicate_upstream_calls(monkeypatch):
    monkeypatch.setenv("CACHE_TTL_SECONDS", "60")
    get_settings.cache_clear()
    cache.clear()

    route = respx.get("https://example.test/api").mock(
        return_value=httpx.Response(200, json={"n": 1})
    )

    async def call():
        return await fetch("test", "https://example.test/api", {})

    first = await cache.get_or_set("k", call)
    second = await cache.get_or_set("k", call)

    assert first == second == {"n": 1}
    assert route.call_count == 1

    cache.clear()
    get_settings.cache_clear()
