import pytest

from app.domain.calc import estimate_size
from app.domain.zoning import ZONE_LIMITS, lookup_limit, normalize_zone_name


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("제2종일반주거지역", "res_gen_2"),
        ("2종일반주거", "res_gen_2"),
        ("제 2 종 일반주거지역", "res_gen_2"),
        ("제2종일반주거지역(7층이하)", "res_gen_2"),
        ("제2종일반주거지역（7층이하）", "res_gen_2"),  # 전각 괄호
        ("제Ⅱ종일반주거지역", "res_gen_2"),
        ("일반상업지역", "com_general"),
        ("자연녹지지역", "green_natural"),
        ("계획관리지역", "mgmt_plan"),
        ("준공업지역", "ind_semi"),
        ("도시지역,제3종일반주거지역", "res_gen_3"),
    ],
)
def test_normalize_zone_name_handles_real_world_variants(raw, expected):
    assert normalize_zone_name(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "가축사육제한구역", "대공방어협조구역"])
def test_normalize_zone_name_returns_none_for_non_use_zones(raw):
    assert normalize_zone_name(raw) is None


def test_longer_alias_wins_over_shorter_substring():
    # '준주거지역' 이 '제1종일반주거지역' 안에 부분 문자열로 걸리면 안 된다.
    assert normalize_zone_name("제1종일반주거지역") == "res_gen_1"


def test_limits_match_enforcement_decree_values():
    # 국토계획법 시행령 제84조/제85조 대표값 검증
    assert ZONE_LIMITS["res_gen_2"].building_coverage_max == 60
    assert ZONE_LIMITS["res_gen_2"].floor_area_ratio_max == 250
    assert ZONE_LIMITS["res_gen_3"].building_coverage_max == 50
    assert ZONE_LIMITS["res_gen_3"].floor_area_ratio_max == 300
    assert ZONE_LIMITS["com_central"].building_coverage_max == 90
    assert ZONE_LIMITS["com_central"].floor_area_ratio_max == 1500
    assert ZONE_LIMITS["green_natural"].building_coverage_max == 20
    assert ZONE_LIMITS["mgmt_plan"].building_coverage_max == 40


def test_all_zones_have_sane_ranges():
    for zone in ZONE_LIMITS.values():
        assert 0 < zone.building_coverage_max <= 100, zone.name
        assert zone.floor_area_ratio_min <= zone.floor_area_ratio_max, zone.name


def test_estimate_size_applies_coverage_and_ratio():
    limit = lookup_limit("제2종일반주거지역")
    result = estimate_size(limit, 330.0)
    assert result is not None
    assert result.max_building_area_m2 == pytest.approx(198.0)  # 330 x 60%
    assert result.max_total_floor_area_m2 == pytest.approx(825.0)  # 330 x 250%
    assert result.approx_max_floors == pytest.approx(4.2, abs=0.05)


@pytest.mark.parametrize("area", [0, -1, None])
def test_estimate_size_skips_missing_area(area):
    assert estimate_size(lookup_limit("일반상업지역"), area) is None
