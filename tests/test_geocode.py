import httpx
import pytest
import respx

from app.services import geocode
from app.utils.http import PublicApiError, close_client


@pytest.fixture(autouse=True)
async def _close_http_client():
    yield
    await close_client()


@respx.mock
async def test_search_addresses_builds_pnu(juso_response):
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(200, json=juso_response)
    )

    results = await geocode.search_addresses("테헤란로 152")

    assert len(results) == 1
    hit = results[0]
    assert hit.pnu == "1168010100107370000"
    assert hit.sigungu == "강남구"
    assert hit.main_no == 737
    assert hit.mountain is False


@respx.mock
async def test_search_addresses_raises_on_api_error_code(juso_response):
    juso_response["results"]["common"] = {
        "errorCode": "E0005",
        "errorMessage": "검색어가 너무 짧습니다.",
    }
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(200, json=juso_response)
    )

    with pytest.raises(PublicApiError) as exc:
        await geocode.search_addresses("가")
    assert "E0005" in str(exc.value)


@respx.mock
async def test_search_addresses_skips_entries_without_pnu_fields(juso_response):
    # 지번 정보가 없는 특수 주소는 PNU 를 만들 수 없으므로 건너뛴다.
    juso_response["results"]["juso"].append(
        {"roadAddr": "세종특별자치시 어딘가", "admCd": "", "lnbrMnnm": ""}
    )
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(200, json=juso_response)
    )

    results = await geocode.search_addresses("테헤란로")
    assert len(results) == 1


async def test_search_addresses_requires_key(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("JUSO_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(PublicApiError, match="JUSO_API_KEY"):
        await geocode.search_addresses("테헤란로 152")


@respx.mock
async def test_geocode_parses_vworld_point():
    respx.get(url__startswith="https://api.vworld.kr/req/address").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "status": "OK",
                    "result": {"point": {"x": "127.0364", "y": "37.5006"}},
                }
            },
        )
    )

    coord = await geocode.geocode("서울특별시 강남구 테헤란로 152")
    assert coord is not None
    assert coord.longitude == pytest.approx(127.0364)
    assert coord.latitude == pytest.approx(37.5006)


@respx.mock
async def test_geocode_returns_none_when_not_found():
    respx.get(url__startswith="https://api.vworld.kr/req/address").mock(
        return_value=httpx.Response(200, json={"response": {"status": "NOT_FOUND"}})
    )
    assert await geocode.geocode("없는 주소") is None


@respx.mock
async def test_geocode_degrades_gracefully_on_upstream_failure():
    # 지오코더는 일 호출 제한이 있어 실패해도 파이프라인 전체를 막지 않아야 한다.
    respx.get(url__startswith="https://api.vworld.kr/req/address").mock(
        return_value=httpx.Response(429, text="quota exceeded")
    )
    assert await geocode.geocode("서울특별시 강남구 테헤란로 152") is None
