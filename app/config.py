"""애플리케이션 설정.

모든 외부 API 키와 엔드포인트를 한 곳에서 관리한다.
공공 API 는 운영 주체가 경로/버전을 변경하는 경우가 있어 base URL 도
환경변수로 덮어쓸 수 있게 노출해 두었다.
"""

import re
from functools import lru_cache
from urllib.parse import unquote

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 공공데이터포털은 같은 키를 Encoding/Decoding 두 가지 형태로 제공한다.
# httpx 가 쿼리스트링을 인코딩하므로 Decoding 형태를 써야 하는데, 포털 화면에서
# Encoding 값을 그대로 복사해 넣는 실수가 흔하다(그러면 %2B 가 %252B 로 이중
# 인코딩되어 SERVICE_KEY_IS_NOT_REGISTERED_ERROR 가 난다).
# base64 키에 등장할 수 있는 문자(+ / =)의 퍼센트 인코딩이 보이면 디코딩한다.
_PERCENT_ENCODED = re.compile(r"%(2B|2F|3D)", re.IGNORECASE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 인증키 ---
    juso_api_key: str = ""
    vworld_api_key: str = ""
    data_go_kr_service_key: str = ""
    law_oc: str = ""

    # --- 엔드포인트 ---
    juso_base_url: str = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
    vworld_base_url: str = "https://api.vworld.kr/req/address"
    # 국가공간정보포털(NSDI) 오픈API. 토지이용계획/토지특성 속성 조회에 사용.
    nsdi_base_url: str = "http://apis.data.go.kr/1611000/nsdi"
    # 건축HUB 건축물대장 서비스.
    bldrgst_base_url: str = "http://apis.data.go.kr/1613000/BldRgstHubService"
    # 국가법령정보 공동활용 DRF (lawSearch.do / lawService.do).
    law_base_url: str = "https://www.law.go.kr/DRF"

    # --- 동작 설정 ---
    http_timeout: float = 10.0
    # 공공기관 서버는 정상 응답이 1초 내외지만 연결 자체가 간헐적으로 끊긴다.
    # 타임아웃을 늘리는 것보다 재시도를 늘리는 편이 회복률이 높다.
    http_max_retries: int = 3
    cache_ttl_seconds: int = 3600
    log_level: str = "INFO"

    @field_validator("data_go_kr_service_key", mode="after")
    @classmethod
    def _normalize_service_key(cls, value: str) -> str:
        """Encoding 키를 붙여넣어도 동작하도록 Decoding 형태로 통일한다."""
        if value and _PERCENT_ENCODED.search(value):
            return unquote(value)
        return value

    def missing_keys(self) -> list[str]:
        """설정되지 않은 인증키 이름 목록. /health 에서 노출한다."""
        required = {
            "JUSO_API_KEY": self.juso_api_key,
            "VWORLD_API_KEY": self.vworld_api_key,
            "DATA_GO_KR_SERVICE_KEY": self.data_go_kr_service_key,
            "LAW_OC": self.law_oc,
        }
        return [name for name, value in required.items() if not value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
