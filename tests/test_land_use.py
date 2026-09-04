import httpx
import pytest
import respx

from app.models import ZoneDesignation
from app.services import land_use
from app.services.land_use import (
    build_designations,
    extract_records,
    pick_primary_zone,
)
from app.utils.http import close_client


@pytest.fixture(autouse=True)
async def _close_http_client():
    yield
    await close_client()


def test_extract_records_handles_nsdi_wrapper():
    payload = {
        "landUses": {
            "totalCount": "2",
            "field": [
                {"pnu": "1168010100107370000", "prposAreaDstrcCodeNm": "제3종일반주거지역"},
                {"pnu": "1168010100107370000", "prposAreaDstrcCodeNm": "도시지역"},
            ],
        }
    }
    assert len(extract_records(payload)) == 2


def test_extract_records_handles_data_go_kr_wrapper():
    payload = {
        "response": {
            "header": {"resultCode": "00"},
            "body": {"items": {"item": [{"lndcgrCodeNm": "대"}]}, "totalCount": 1},
        }
    }
    records = extract_records(payload)
    assert records == [{"lndcgrCodeNm": "대"}]


def test_extract_records_handles_single_record_as_dict():
    payload = {"landUses": {"field": {"prposAreaDstrcCodeNm": "일반상업지역"}}}
    assert extract_records(payload) == [{"prposAreaDstrcCodeNm": "일반상업지역"}]


def test_extract_records_tolerates_empty_and_bad_payloads():
    assert extract_records(None) == []
    assert extract_records({}) == []
    assert extract_records("not json") == []


def test_build_designations_flags_use_districts_and_conflict():
    records = [
        {"prposAreaDstrcCodeNm": "제3종일반주거지역", "prposAreaDstrcCode": "UQA113", "cnflcAt": "0"},
        {"prposAreaDstrcCodeNm": "대공방어협조구역", "cnflcAt": "1"},
        {"prposAreaDstrcCodeNm": "제3종일반주거지역", "prposAreaDstrcCode": "UQA113", "cnflcAt": "0"},
    ]
    designations = build_designations(records)

    assert len(designations) == 2  # 중복 제거
    assert designations[0].is_use_district is True
    assert designations[0].conflict is False
    assert designations[1].is_use_district is False
    assert designations[1].conflict is True


def test_pick_primary_zone_prefers_non_conflicting_use_district():
    designations = [
        ZoneDesignation(name="자연녹지지역", conflict=True, is_use_district=True),
        ZoneDesignation(name="제2종일반주거지역", conflict=False, is_use_district=True),
        ZoneDesignation(name="가축사육제한구역", conflict=False, is_use_district=False),
    ]
    assert pick_primary_zone(designations) == "제2종일반주거지역"


def test_pick_primary_zone_returns_none_without_use_district():
    designations = [ZoneDesignation(name="가축사육제한구역", is_use_district=False)]
    assert pick_primary_zone(designations) is None


@respx.mock
async def test_build_overview_merges_both_apis():
    respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landUses": {
                    "field": [
                        {"prposAreaDstrcCodeNm": "제2종일반주거지역", "cnflcAt": "0"},
                        {"prposAreaDstrcCodeNm": "도시지역", "cnflcAt": "0"},
                    ]
                }
            },
        )
    )
    respx.get(url__regex=r".*getLandCharacteristics.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landCharacteristics": {
                    "field": [
                        {"lndcgrCodeNm": "대", "lndpclAr": "330.5", "pblntfPclnd": "12500000"}
                    ]
                }
            },
        )
    )

    overview = await land_use.build_overview("1168010100107370000")

    assert overview.jibun == "737"
    assert overview.land_category == "대"
    assert overview.area_m2 == pytest.approx(330.5)
    assert overview.official_price_krw == 12500000
    assert overview.primary_zone == "제2종일반주거지역"
    assert overview.primary_zone_normalized == "제2종일반주거지역"


@respx.mock
async def test_build_overview_survives_land_use_api_failure():
    respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(500, text="server error")
    )
    respx.get(url__regex=r".*getLandCharacteristics.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landCharacteristics": {
                    "field": [
                        {
                            "lndcgrCodeNm": "대",
                            "lndpclAr": "200",
                            "prposArea1Nm": "일반상업지역",
                        }
                    ]
                }
            },
        )
    )

    overview = await land_use.build_overview("1168010100107370000")

    # 토지이용계획이 실패해도 토지특성의 용도지역으로 보완된다.
    assert overview.primary_zone == "일반상업지역"
    assert overview.area_m2 == pytest.approx(200)
    assert any("토지이용계획 조회 실패" in w for w in overview.warnings)


@respx.mock
async def test_build_overview_warns_on_multiple_use_districts():
    respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landUses": {
                    "field": [
                        {"prposAreaDstrcCodeNm": "제1종일반주거지역", "cnflcAt": "0"},
                        {"prposAreaDstrcCodeNm": "자연녹지지역", "cnflcAt": "0"},
                    ]
                }
            },
        )
    )
    respx.get(url__regex=r".*getLandCharacteristics.*").mock(
        return_value=httpx.Response(200, json={"landCharacteristics": {"field": []}})
    )

    overview = await land_use.build_overview("1168010100107370000")

    assert any("용도지역이 둘 이상" in w for w in overview.warnings)
    # 건폐율이 높은 쪽(1종일반주거 60%)을 대표로 선택
    assert overview.primary_zone == "제1종일반주거지역"


@respx.mock
async def test_land_use_request_targets_vworld_ned_with_key_and_domain():
    """토지 속성 API 의 호출 지점과 인증 방식을 고정한다.

    이 두 API 는 공공데이터포털이 아니라 브이월드 NED 게이트웨이에서
    서비스되고, serviceKey 가 아니라 key + domain 으로 인증한다.
    apis.data.go.kr 쪽 경로로 되돌아가면 게이트웨이가 존재하지 않는 경로로
    보고 NO_OPENAPI_SERVICE_ERROR(코드 12) 를 돌려주므로 회귀를 막는다.
    """
    route = respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(200, json={"landUses": {"field": []}})
    )

    await land_use.fetch_land_use_attrs("1168010100107370000")

    request = route.calls.last.request
    assert request.url.host == "api.vworld.kr"
    assert request.url.path == "/ned/data/getLandUseAttr"

    params = request.url.params
    assert params["key"] == "TEST-VWORLD-KEY"
    assert params["domain"] == "localhost"
    assert params["pnu"] == "1168010100107370000"
    # serviceKey 로 되돌아가면 NED 게이트웨이가 인증하지 못한다.
    assert "serviceKey" not in params


@respx.mock
async def test_nsdi_key_prefers_dedicated_key_over_vworld_key(monkeypatch):
    """NSDI 전용 키가 있으면 그쪽을 쓰고, 없을 때만 브이월드 키로 대체한다."""
    from app.config import get_settings

    monkeypatch.setenv("NSDI_API_KEY", "TEST-NSDI-KEY")
    monkeypatch.setenv("NSDI_DOMAIN", "example.com")
    get_settings.cache_clear()

    route = respx.get(url__regex=r".*getLandCharacteristics.*").mock(
        return_value=httpx.Response(200, json={"landCharacteristics": {"field": []}})
    )

    await land_use.fetch_land_characteristics("1168010100107370000")

    params = route.calls.last.request.url.params
    assert params["key"] == "TEST-NSDI-KEY"
    assert params["domain"] == "example.com"
