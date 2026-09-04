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


@respx.mock
async def test_connect_failure_is_flagged_as_network_error():
    # 프록시/방화벽 차단은 인증키 문제와 조치가 다르므로 구분되어야 한다.
    respx.get("https://example.test/api").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert exc.value.network is True
    assert "연결하지 못했습니다" in exc.value.detail


@respx.mock
async def test_proxy_failure_is_flagged_as_network_error():
    respx.get("https://example.test/api").mock(
        side_effect=httpx.ProxyError("403 Forbidden")
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert exc.value.network is True


@respx.mock
async def test_auth_failure_is_not_flagged_as_network_error():
    respx.get("https://example.test/api").mock(
        return_value=httpx.Response(401, text="unauthorized")
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert exc.value.network is False


@respx.mock
async def test_client_error_includes_response_body_reason():
    # 게이트웨이/API 가 거부 사유를 본문에 실어 보내는 경우가 많다.
    # 이걸 버리면 원인 파악이 늦어진다 (실제로 겪은 문제).
    respx.get("https://example.test/api").mock(
        return_value=httpx.Response(
            403,
            text="Host not in allowlist: apis.data.go.kr. "
            "Add this host to your network egress settings to allow access.",
        )
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert "Host not in allowlist" in exc.value.detail


@respx.mock
async def test_server_error_body_is_stripped_of_html(fast_retries):
    respx.get("https://example.test/api").mock(
        return_value=httpx.Response(
            502,
            text="<html><body><h1>502 Bad Gateway</h1>\n"
            "The server returned an invalid or incomplete response.\n</body></html>",
        )
    )

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    detail = exc.value.detail
    assert "502 Bad Gateway" in detail
    assert "<html>" not in detail  # 태그는 제거
    assert "\n" not in detail  # 한 줄로 정리


@respx.mock
async def test_empty_error_body_adds_nothing(fast_retries):
    respx.get("https://example.test/api").mock(return_value=httpx.Response(404, text=""))

    with pytest.raises(PublicApiError) as exc:
        await fetch("test", "https://example.test/api", {})

    assert "응답:" not in exc.value.detail


@respx.mock
async def test_status_code_survives_retry_exhaustion():
    """재시도를 다 써도 마지막 상류 상태코드를 잃지 않아야 한다.

    호출자(doctor)는 502/503 인지에 따라 '인증키 문제'와 '호출 지점 차단'을
    갈라 안내한다. 상태코드가 None 으로 떨어지면 그 구분이 무너진다.
    """
    respx.get(url__startswith="https://example.test").mock(
        return_value=httpx.Response(502, text="502 Bad Gateway")
    )

    with pytest.raises(PublicApiError) as excinfo:
        await fetch("test", "https://example.test/api", {})

    assert excinfo.value.status_code == 502
    # 상류에 닿아서 502 를 받은 것이므로 '네트워크 미도달' 은 아니다.
    assert excinfo.value.network is False
