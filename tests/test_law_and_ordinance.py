import httpx
import pytest
import respx

from app.services import law, ordinance
from app.services.law import CORE_ARTICLES, ArticleRef, extract_drf_records
from app.utils.http import PublicApiError, close_client


@pytest.fixture(autouse=True)
async def _close_http_client():
    yield
    await close_client()


def test_records_reads_law_search_shape():
    payload = {
        "LawSearch": {
            "target": "law",
            "totalCnt": "2",
            "law": [{"법령명한글": "건축법"}, {"법령명한글": "건축법 시행령"}],
        }
    }
    assert len(extract_drf_records(payload)) == 2


def test_records_reads_ordin_search_shape():
    payload = {
        "OrdinSearch": {
            "totalCnt": "1",
            "law": [{"자치법규명": "서울특별시 강남구 도시계획 조례"}],
        }
    }
    assert extract_drf_records(payload)[0]["자치법규명"] == "서울특별시 강남구 도시계획 조례"


def test_records_reads_single_record_shape():
    payload = {"OrdinSearch": {"law": {"자치법규명": "강남구 건축 조례"}}}
    assert extract_drf_records(payload) == [{"자치법규명": "강남구 건축 조례"}]


def test_records_tolerates_empty():
    assert extract_drf_records({}) == []
    assert extract_drf_records({"OrdinSearch": {"totalCnt": "0", "law": []}}) == []


def test_article_ref_builds_jo_param_and_link():
    ref = ArticleRef("건축법", 55, "건축물의 건폐율")
    assert ref.jo_param == "005500"
    assert "제55조" in ref.link


def test_core_articles_cover_coverage_and_ratio_bases():
    names = {(a.law_name, a.article_no) for a in CORE_ARTICLES}
    assert ("건축법", 55) in names
    assert ("건축법", 56) in names
    assert ("국토의 계획 및 이용에 관한 법률 시행령", 84) in names
    assert ("국토의 계획 및 이용에 관한 법률 시행령", 85) in names


async def test_core_statutes_without_content_makes_no_http_calls():
    # 링크만 필요할 때는 외부 호출이 없어야 한다(일 호출 한도 절약).
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(url__startswith="https://www.law.go.kr").mock(
            return_value=httpx.Response(200, json={})
        )
        statutes = await law.core_statutes(with_content=False)
    assert not route.called
    assert len(statutes) == len(CORE_ARTICLES)
    assert all(s.link for s in statutes)
    assert all(s.content is None for s in statutes)


@respx.mock
async def test_fetch_article_extracts_text():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawService.do").mock(
        return_value=httpx.Response(
            200,
            json={
                "법령": {
                    "조문": {
                        "조문단위": {
                            "조문번호": "55",
                            "조문내용": "제55조(건축물의 건폐율) <b>대지면적</b>에 대한 ...",
                        }
                    }
                }
            },
        )
    )

    article = await law.fetch_article(ArticleRef("건축법", 55, "건축물의 건폐율"))

    assert article.content is not None
    assert "건폐율" in article.content
    assert "<b>" not in article.content  # HTML 태그 제거
    assert article.link is not None


@respx.mock
async def test_fetch_article_falls_back_to_link_on_failure():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawService.do").mock(
        return_value=httpx.Response(500, text="error")
    )

    article = await law.fetch_article(ArticleRef("건축법", 55, "건축물의 건폐율"))

    assert article.content is None
    assert article.article_no == "제55조"
    assert article.link is not None


@respx.mock
async def test_find_for_site_filters_out_other_local_governments():
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
                        },
                        {
                            "자치법규명": "부산광역시 해운대구 도시계획 조례",
                            "지자체기관명": "해운대구",
                            "자치법규ID": "2",
                        },
                    ]
                }
            },
        )
    )

    hits, warnings = await ordinance.find_for_site("서울특별시", "강남구")

    titles = [h.title for h in hits]
    assert "서울특별시 강남구 도시계획 조례" in titles
    assert all("해운대구" not in t for t in titles)
    assert hits[0].link.startswith("https://www.law.go.kr/")
    assert warnings == []


@respx.mock
async def test_find_for_site_reports_upstream_failure_as_warning():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawSearch.do").mock(
        return_value=httpx.Response(500, text="error")
    )

    hits, warnings = await ordinance.find_for_site("서울특별시", "강남구")

    assert hits == []
    assert warnings  # 예외 대신 경고로 돌려준다


async def test_find_for_site_without_region_returns_warning():
    hits, warnings = await ordinance.find_for_site(None, None)
    assert hits == []
    assert "지자체를 특정할 수 없어" in warnings[0]


# --- 실제 API 응답에서 확인된 인증 실패 형태 ---
# 국가법령정보는 OC 오류나 IP 미등록 시에도 HTTP 200 을 준다.
# 실측 응답으로 회귀 테스트를 만들어 둔다.
_REAL_AUTH_ERROR = {
    "result": "사용자 정보 검증에 실패하였습니다.",
    "msg": (
        "OPEN API 호출 시 사용자 검증을 위하여 정확한 서버장비의 "
        "IP주소 및 도메인주소를 등록해 주세요."
    ),
}


@respx.mock
async def test_search_laws_surfaces_auth_error_returned_with_http_200():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawSearch.do").mock(
        return_value=httpx.Response(200, json=_REAL_AUTH_ERROR)
    )

    with pytest.raises(PublicApiError) as exc:
        await law.search_laws("건축법")

    # '결과 0건' 으로 뭉개지 말고 실제 사유가 드러나야 한다.
    assert "사용자 정보 검증에 실패" in exc.value.detail
    assert "IP주소" in exc.value.detail


@respx.mock
async def test_ordinance_search_surfaces_same_auth_error():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawSearch.do").mock(
        return_value=httpx.Response(200, json=_REAL_AUTH_ERROR)
    )

    hits, warnings = await ordinance.find_for_site("서울특별시", "강남구")

    assert hits == []
    assert any("사용자 정보 검증에 실패" in w for w in warnings)


@respx.mock
async def test_fetch_article_falls_back_to_link_on_auth_error():
    respx.get(url__startswith="https://www.law.go.kr/DRF/lawService.do").mock(
        return_value=httpx.Response(200, json=_REAL_AUTH_ERROR)
    )

    article = await law.fetch_article(ArticleRef("건축법", 55, "건축물의 건폐율"))

    assert article.content is None
    assert article.link is not None  # 링크는 항상 제공


def test_normal_payload_is_not_mistaken_for_auth_error():
    # 정상 응답에 'result' 키가 있어도 '실패' 가 없으면 통과해야 한다.
    law.raise_if_auth_error({"LawSearch": {"law": [{"법령명한글": "건축법"}]}})
    law.raise_if_auth_error({"result": "정상"})
    law.raise_if_auth_error(None)
