"""테스트 공통 설정.

외부 공공 API 를 실제로 호출하지 않도록 인증키를 더미로 주입하고,
캐시를 매 테스트마다 비운다.
"""

import pytest

from app.config import get_settings
from app.utils import cache


@pytest.fixture(autouse=True)
def _test_settings(monkeypatch):
    monkeypatch.setenv("JUSO_API_KEY", "TEST-JUSO-KEY")
    monkeypatch.setenv("VWORLD_API_KEY", "TEST-VWORLD-KEY")
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "TEST-DATA-KEY")
    monkeypatch.setenv("LAW_OC", "testoc")
    # 테스트 간섭을 막기 위해 캐시는 끈다.
    monkeypatch.setenv("CACHE_TTL_SECONDS", "0")
    # 재시도 백오프로 테스트가 느려지지 않게 한다.
    # 재시도 동작 자체는 tests/test_http.py 에서 별도로 검증한다.
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")
    get_settings.cache_clear()
    cache.clear()
    yield
    get_settings.cache_clear()
    cache.clear()


@pytest.fixture
def juso_response():
    """도로명주소 API 성공 응답 (서울 강남구 예시)."""
    return {
        "results": {
            "common": {
                "errorCode": "0",
                "errorMessage": "정상",
                "totalCount": "1",
            },
            "juso": [
                {
                    "roadAddr": "서울특별시 강남구 테헤란로 152 (역삼동)",
                    "jibunAddr": "서울특별시 강남구 역삼동 737",
                    "zipNo": "06236",
                    "siNm": "서울특별시",
                    "sggNm": "강남구",
                    "emdNm": "역삼동",
                    "admCd": "1168010100",
                    "lnbrMnnm": "737",
                    "lnbrSlno": "0",
                    "mtYn": "0",
                }
            ],
        }
    }
