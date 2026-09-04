"""라우터 레벨 통합 테스트. 외부 API 는 모두 모킹한다."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def _mock_upstreams(juso_response, *, zone="제2종일반주거지역", area="330.5"):
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(200, json=juso_response)
    )
    respx.get(url__startswith="https://api.vworld.kr").mock(
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
    respx.get(url__regex=r".*LandUseService.*").mock(
        return_value=httpx.Response(
            200,
            json={"landUses": {"field": [{"prposAreaDstrcCodeNm": zone, "cnflcAt": "0"}]}},
        )
    )
    respx.get(url__regex=r".*LandCharacteristicsService.*").mock(
        return_value=httpx.Response(
            200,
            json={"landCharacteristics": {"field": [{"lndcgrCodeNm": "대", "lndpclAr": area}]}},
        )
    )
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawSearch.do").mock(
        return_value=httpx.Response(
            200,
            json={
                "OrdinSearch": {
                    "law": [
                        {
                            "자치법규명": "서울특별시 강남구 도시계획 조례",
                            "지자체기관명": "강남구",
                            "자치법규ID": "1",
                            "자치법규상세링크": "/LSW/ordinInfoP.do?ordinSeq=1",
                        }
                    ]
                }
            },
        )
    )


def test_health_reports_key_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["missing_keys"] == []


@respx.mock
def test_address_search_endpoint(client, juso_response):
    _mock_upstreams(juso_response)
    response = client.get("/api/v1/address/search", params={"q": "테헤란로 152"})
    assert response.status_code == 200
    assert response.json()[0]["pnu"] == "1168010100107370000"


@respx.mock
def test_site_endpoint_returns_full_report(client, juso_response):
    _mock_upstreams(juso_response)

    response = client.get("/api/v1/site", params={"address": "테헤란로 152"})

    assert response.status_code == 200
    body = response.json()
    assert body["address"]["pnu"] == "1168010100107370000"
    assert body["coordinate"]["latitude"] == pytest.approx(37.5006)
    assert body["overview"]["land_category"] == "대"
    assert body["overview"]["primary_zone_normalized"] == "제2종일반주거지역"

    limit = body["legal_limit"]
    assert limit["building_coverage_max_pct"] == 60
    assert limit["floor_area_ratio_max_pct"] == 250
    assert "조례" in limit["note"]

    estimate = body["size_estimate"]
    assert estimate["max_building_area_m2"] == pytest.approx(198.3)  # 330.5 x 60%
    assert estimate["max_total_floor_area_m2"] == pytest.approx(826.25)  # 330.5 x 250%

    assert body["statutes"]  # 근거 조문 링크
    assert body["ordinance_candidates"][0]["local_gov"] == "강남구"
    assert "토지이음" in body["references"]


@respx.mock
def test_site_endpoint_404_when_address_not_found(client, juso_response):
    juso_response["results"]["juso"] = []
    juso_response["results"]["common"]["totalCount"] = "0"
    _mock_upstreams(juso_response)

    response = client.get("/api/v1/site", params={"address": "없는주소12345"})
    assert response.status_code == 404


@respx.mock
def test_site_endpoint_502_on_upstream_failure(client):
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    response = client.get("/api/v1/site", params={"address": "테헤란로 152"})
    assert response.status_code == 502


@respx.mock
def test_site_endpoint_reports_unknown_zone_in_warnings(client, juso_response):
    _mock_upstreams(juso_response, zone="가축사육제한구역")

    response = client.get("/api/v1/site", params={"address": "테헤란로 152"})

    body = response.json()
    assert body["legal_limit"] is None
    assert body["size_estimate"] is None
    assert any("용도지역을 확인하지 못해" in w for w in body["warnings"])


@respx.mock
def test_site_by_pnu_endpoint(client):
    _mock_upstreams({"results": {"common": {"errorCode": "0"}, "juso": []}})

    response = client.get("/api/v1/site/pnu/1168010100107370000")

    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["jibun"] == "737"
    assert body["coordinate"] is None  # PNU 직접 조회는 지오코딩을 건너뛴다


def test_site_by_pnu_rejects_malformed_pnu(client):
    response = client.get("/api/v1/site/pnu/123")
    assert response.status_code == 422


def test_limits_table_endpoint(client):
    response = client.get("/api/v1/limits")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 21  # 국토계획법 시행령상 용도지역 21종
    names = {row["zone_name"] for row in body}
    assert "제3종일반주거지역" in names
    assert "자연환경보전지역" in names


def test_estimate_endpoint(client):
    response = client.get(
        "/api/v1/limits/estimate", params={"zone": "일반상업지역", "area_m2": 500}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["max_building_area_m2"] == pytest.approx(400.0)  # 500 x 80%
    assert body["max_total_floor_area_m2"] == pytest.approx(6500.0)  # 500 x 1300%


def test_estimate_endpoint_rejects_unknown_zone(client):
    response = client.get(
        "/api/v1/limits/estimate", params={"zone": "존재하지않는지역", "area_m2": 500}
    )
    assert response.status_code == 422


def test_ordinances_endpoint_requires_a_region(client):
    assert client.get("/api/v1/ordinances").status_code == 422
