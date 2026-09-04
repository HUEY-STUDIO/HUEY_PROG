"""진단 도구 테스트.

실제 네트워크가 막힌 환경에서도 도구가 옳게 동작하는지 확인한다.
정상 응답을 모두 모킹해 '전체 통과' 경로를, 차단 상황을 모킹해
'네트워크 문제'로 진단하는지를 각각 검증한다.
"""

import httpx
import respx

from app.doctor import Doctor


def _mock_all_upstreams_ok(juso_response):
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        return_value=httpx.Response(200, json=juso_response)
    )
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
    respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landUses": {
                    "field": [{"prposAreaDstrcCodeNm": "제2종일반주거지역", "cnflcAt": "0"}]
                }
            },
        )
    )
    respx.get(url__regex=r".*getLandCharacteristics.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "landCharacteristics": {
                    "field": [{"lndcgrCodeNm": "대", "lndpclAr": "330.5"}]
                }
            },
        )
    )
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawSearch.do").mock(
        side_effect=_law_search_router
    )


def _law_search_router(request):
    """target 파라미터에 따라 법령/자치법규 응답을 나눠 돌려준다."""
    if request.url.params.get("target") == "ordin":
        return httpx.Response(
            200,
            json={
                "OrdinSearch": {
                    "law": [
                        {
                            "자치법규명": "서울특별시 강남구 도시계획 조례",
                            "지자체기관명": "강남구",
                            "자치법규ID": "1",
                        }
                    ]
                }
            },
        )
    return httpx.Response(
        200, json={"LawSearch": {"law": [{"법령명한글": "건축법"}]}}
    )


@respx.mock
async def test_doctor_passes_when_all_apis_healthy(juso_response, capsys):
    _mock_all_upstreams_ok(juso_response)

    doctor = Doctor("서울특별시 강남구 테헤란로 152", raw=False)
    exit_code = await doctor.run()

    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert doctor.failures == []
    assert "전체 통과" in out
    assert "1168010100107370000" in out  # PNU
    assert "제2종일반주거지역" in out


@respx.mock
async def test_doctor_reports_network_problem_not_key_problem(juso_response, capsys):
    _mock_all_upstreams_ok(juso_response)
    respx.get(url__startswith="https://business.juso.go.kr").mock(
        side_effect=httpx.ProxyError("403 Forbidden")
    )

    doctor = Doctor("서울특별시 강남구 테헤란로 152", raw=False)
    exit_code = await doctor.run()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "juso" in doctor.failures
    assert "인증키가 아니라 네트워크 문제입니다" in out
    # 주소 조회가 실패하면 뒤 단계는 건너뛴다.
    assert "[SKIP]" in out


@respx.mock
async def test_doctor_flags_unparseable_response_for_reporting(juso_response, capsys):
    _mock_all_upstreams_ok(juso_response)
    # 응답은 200 이지만 구조가 예상과 다른 경우 (엔드포인트 변경 등)
    respx.get(url__regex=r".*getLandUseAttr.*").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    doctor = Doctor("서울특별시 강남구 테헤란로 152", raw=False)
    await doctor.run()

    out = capsys.readouterr().out
    assert "레코드를 찾지 못했습니다" in out
    assert "--raw" in out


async def test_doctor_stops_early_when_keys_missing(monkeypatch, capsys):
    from app.config import get_settings

    monkeypatch.setenv("LAW_OC", "")
    get_settings.cache_clear()

    doctor = Doctor("서울특별시 강남구 테헤란로 152", raw=False)
    exit_code = await doctor.run()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "LAW_OC" in out
    assert "인증키가 없어 나머지 검사를 건너뜁니다" in out
    get_settings.cache_clear()
