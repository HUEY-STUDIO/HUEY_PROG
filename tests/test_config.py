import pytest

from app.config import Settings


@pytest.fixture
def clean_env(monkeypatch):
    for key in (
        "JUSO_API_KEY",
        "VWORLD_API_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "LAW_OC",
    ):
        monkeypatch.delenv(key, raising=False)


def test_encoding_service_key_is_normalized_to_decoding_form(clean_env, monkeypatch):
    # 포털 화면에서 Encoding 키를 그대로 붙여넣는 실수가 흔하다.
    # 그대로 두면 httpx 가 %2B 를 %252B 로 이중 인코딩해 인증에 실패한다.
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc%2Bdef%2Fghi%3D%3D")
    settings = Settings(_env_file=None)
    assert settings.data_go_kr_service_key == "abc+def/ghi=="


def test_decoding_service_key_is_left_untouched(clean_env, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc+def/ghi==")
    settings = Settings(_env_file=None)
    assert settings.data_go_kr_service_key == "abc+def/ghi=="


def test_service_key_without_special_chars_is_untouched(clean_env, monkeypatch):
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "plainkey123")
    settings = Settings(_env_file=None)
    assert settings.data_go_kr_service_key == "plainkey123"


def test_percent_sign_unrelated_to_encoding_is_preserved(clean_env, monkeypatch):
    # %2B/%2F/%3D 가 없으면 디코딩하지 않는다 (키에 % 가 진짜로 들어있을 수 있다).
    monkeypatch.setenv("DATA_GO_KR_SERVICE_KEY", "abc%20def")
    settings = Settings(_env_file=None)
    assert settings.data_go_kr_service_key == "abc%20def"


def test_missing_keys_lists_unset_credentials(clean_env, monkeypatch):
    monkeypatch.setenv("JUSO_API_KEY", "x")
    settings = Settings(_env_file=None)
    missing = settings.missing_keys()
    assert "JUSO_API_KEY" not in missing
    assert set(missing) == {"VWORLD_API_KEY", "DATA_GO_KR_SERVICE_KEY", "LAW_OC"}
