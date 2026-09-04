import pytest

from app.domain.pnu import PnuError, build_pnu, parse_pnu


def test_build_pnu_pads_main_and_sub_numbers():
    pnu = build_pnu("1168010100", 737, 0)
    assert pnu == "1168010100107370000"
    assert len(pnu) == 19


def test_build_pnu_marks_mountain_parcels():
    normal = build_pnu("4173025328", 12, 3)
    mountain = build_pnu("4173025328", 12, 3, mountain=True)
    assert normal[10] == "1"
    assert mountain[10] == "2"


def test_build_pnu_accepts_string_jibun_from_api():
    # 도로명주소 API 는 본번/부번을 문자열로 준다.
    assert build_pnu("1168010100", "737", "12") == "1168010100107370012"


def test_build_pnu_treats_blank_sub_number_as_zero():
    assert build_pnu("1168010100", "737", "") == "1168010100107370000"


@pytest.mark.parametrize(
    "ld_code, main, sub",
    [
        ("116801010", 737, 0),  # 9자리
        ("11680101000", 737, 0),  # 11자리
        ("11680A0100", 737, 0),  # 숫자 아님
        ("1168010100", 10000, 0),  # 본번 범위 초과
        ("1168010100", 737, 10000),  # 부번 범위 초과
    ],
)
def test_build_pnu_rejects_malformed_input(ld_code, main, sub):
    with pytest.raises(PnuError):
        build_pnu(ld_code, main, sub)


def test_parse_pnu_roundtrip():
    parsed = parse_pnu("1168010100107370012")
    assert parsed.ld_code == "1168010100"
    assert parsed.sido_code == "11"
    assert parsed.sgg_code == "11680"
    assert parsed.mountain is False
    assert parsed.main_no == 737
    assert parsed.sub_no == 12
    assert parsed.jibun == "737-12"


def test_parse_pnu_formats_mountain_jibun():
    parsed = parse_pnu(build_pnu("4173025328", 12, 0, mountain=True))
    assert parsed.mountain is True
    assert parsed.jibun == "산 12"


@pytest.mark.parametrize("bad", ["", "123", "1168010100107370012X", "1168010100307370012"])
def test_parse_pnu_rejects_bad_codes(bad):
    with pytest.raises(PnuError):
        parse_pnu(bad)
