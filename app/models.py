"""API 응답 스키마."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddressCandidate(BaseModel):
    """도로명주소 API 검색 결과 1건."""

    road_address: str = Field(description="도로명주소")
    jibun_address: str = Field(description="지번주소")
    zip_code: str | None = Field(default=None, description="우편번호")
    sido: str | None = Field(default=None, description="시도명")
    sigungu: str | None = Field(default=None, description="시군구명")
    eupmyeondong: str | None = Field(default=None, description="읍면동명")
    ld_code: str = Field(description="법정동코드 10자리")
    mountain: bool = Field(default=False, description="산(임야) 여부")
    main_no: int = Field(description="지번 본번")
    sub_no: int = Field(default=0, description="지번 부번")
    pnu: str = Field(description="필지고유번호 19자리")


class Coordinate(BaseModel):
    longitude: float = Field(description="경도 (EPSG:4326)")
    latitude: float = Field(description="위도 (EPSG:4326)")
    source: str = Field(default="vworld", description="좌표 출처")


class ZoneDesignation(BaseModel):
    """토지이용계획에 등재된 지역·지구 1건."""

    name: str = Field(description="지역·지구 명칭 원문")
    code: str | None = Field(default=None, description="지역·지구 코드")
    conflict: bool | None = Field(default=None, description="저촉 여부 (저촉=일부만 걸침)")
    registered_at: str | None = Field(default=None, description="등재일자")
    is_use_district: bool = Field(
        default=False, description="국토계획법상 용도지역(건폐율/용적률 결정)인지 여부"
    )


class SiteOverview(BaseModel):
    """대지개요."""

    pnu: str
    jibun: str = Field(description="지번 표기")
    land_category: str | None = Field(default=None, description="지목")
    area_m2: float | None = Field(default=None, description="공부상 대지면적(제곱미터)")
    official_price_krw: int | None = Field(
        default=None, description="개별공시지가(원/제곱미터)"
    )
    primary_zone: str | None = Field(default=None, description="대표 용도지역 원문")
    primary_zone_normalized: str | None = Field(
        default=None, description="정규화된 용도지역 표준 명칭"
    )
    designations: list[ZoneDesignation] = Field(
        default_factory=list, description="토지이용계획상 지역·지구 전체 목록"
    )
    warnings: list[str] = Field(
        default_factory=list, description="조회 중 발생한 부분 실패/주의사항"
    )


class LegalLimit(BaseModel):
    """국가법령이 정한 건폐율/용적률 상한."""

    zone_name: str
    zone_category: str
    building_coverage_max_pct: float = Field(description="건폐율 상한 (%)")
    floor_area_ratio_min_pct: float = Field(description="용적률 하한 (%)")
    floor_area_ratio_max_pct: float = Field(description="용적률 상한 (%)")
    statute_refs: list[str] = Field(description="근거 조문")
    note: str = Field(
        default=(
            "국토계획법 시행령이 정한 범위이며, 실제 적용값은 해당 지자체 "
            "도시계획조례로 이 범위 안에서 별도 규정됩니다. 반드시 조례를 확인하세요."
        )
    )


class SizeEstimateOut(BaseModel):
    site_area_m2: float
    max_building_area_m2: float = Field(description="건축면적 상한 = 대지면적 x 건폐율")
    max_total_floor_area_m2: float = Field(description="연면적 상한 = 대지면적 x 용적률")
    approx_max_floors: float = Field(description="참고 층수 = 용적률 / 건폐율")


class StatuteArticle(BaseModel):
    """국가법령 조문 발췌."""

    law_name: str
    article_no: str | None = None
    article_title: str | None = None
    content: str | None = None
    link: str | None = None


class OrdinanceHit(BaseModel):
    """자치법규(조례) 검색 결과 1건. 자동 판정이 아닌 '후보' 이다."""

    title: str = Field(description="자치법규명")
    local_gov: str | None = Field(default=None, description="지자체명")
    ordinance_id: str | None = Field(default=None, description="자치법규 ID")
    promulgation_date: str | None = Field(default=None, description="공포일자")
    link: str | None = Field(default=None, description="국가법령정보센터 링크")


class SiteReport(BaseModel):
    """주소 1건에 대한 종합 조회 결과."""

    query: str = Field(description="입력 주소")
    address: AddressCandidate
    coordinate: Coordinate | None = None
    overview: SiteOverview
    legal_limit: LegalLimit | None = Field(
        default=None, description="용도지역 판정 실패 시 null"
    )
    size_estimate: SizeEstimateOut | None = None
    statutes: list[StatuteArticle] = Field(default_factory=list)
    ordinance_candidates: list[OrdinanceHit] = Field(default_factory=list)
    references: dict[str, str] = Field(
        default_factory=dict, description="교차검증용 외부 링크 (토지이음 등)"
    )
    warnings: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    missing_keys: list[str] = Field(
        description="설정되지 않은 인증키. 비어 있어야 전체 파이프라인이 동작한다."
    )
    cache_entries: int
