"""FastAPI 진입점.

실행:
    uvicorn app.main:app --reload
문서:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.models import HealthResponse
from app.routers import lookup
from app.utils import cache
from app.utils.http import close_client

DESCRIPTION = """
대한민국 주소를 입력하면 해당 대지의 **대지개요**(용도지역·지목·면적)와
적용 **국가법령**(건축법·국토계획법) 상한, 그리고 관련 **지자체 조례 후보**를
자동으로 모아 보여줍니다.

주의: 건폐율·용적률 산정값은 국토계획법 시행령이 정한 **법정 상한**이며,
실제 적용값은 지자체 도시계획조례로 따로 정해집니다. 조례 결과는 자동 판정이
아니라 **검토 후보**이므로 인허가 판단의 최종 근거로 사용하지 마세요.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    missing = settings.missing_keys()
    if missing:
        logging.getLogger(__name__).warning(
            "인증키가 설정되지 않았습니다: %s — 해당 단계는 동작하지 않습니다. "
            ".env 설정은 docs/API_KEYS.md 참고.",
            ", ".join(missing),
        )
    yield
    await close_client()


app = FastAPI(
    title="국내 건축 대지 법규 자동 조회",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(lookup.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    """서비스 상태와 인증키 설정 여부를 확인한다."""
    settings = get_settings()
    missing = settings.missing_keys()
    return HealthResponse(
        status="ok" if not missing else "degraded",
        missing_keys=missing,
        cache_entries=cache.size(),
    )
