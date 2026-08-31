import os

import ui_common
from streamlit.errors import StreamlitSecretNotFoundError
from tests.fakes import FakePingConnection


class _RaisingSecrets:
    """Mimics st.secrets when no secrets.toml exists anywhere on disk —
    even a plain `in` check raises, confirmed live in the deployed
    container (which has no secrets.toml at all).
    """

    def __contains__(self, _key):
        raise StreamlitSecretNotFoundError("No secrets found")


class _DictSecrets(dict):
    pass


def test_load_oracle_secrets_falls_back_to_env_when_no_secrets_toml_exists(monkeypatch):
    monkeypatch.setattr(ui_common.st, "secrets", _RaisingSecrets())
    monkeypatch.setenv("ORACLE_USER", "USR_FRONTEND")
    monkeypatch.setenv("ORACLE_PASSWORD", "pw")
    monkeypatch.setenv("ORACLE_WALLET_PASSWORD", "wpw")
    monkeypatch.setenv("ORACLE_WALLET_ZIP_B64", "base64data")
    monkeypatch.delenv("ORACLE_DSN", raising=False)

    secrets = ui_common._load_oracle_secrets()

    assert secrets == {
        "user": "USR_FRONTEND",
        "password": "pw",
        "wallet_password": "wpw",
        "dsn": "inteligentesus_high",
        "wallet_zip_b64": "base64data",
    }


def test_load_oracle_secrets_prefers_secrets_toml_when_present(monkeypatch):
    monkeypatch.setattr(
        ui_common.st,
        "secrets",
        _DictSecrets(oracle={"user": "ADMIN", "password": "x", "wallet_password": "y", "dsn": "d", "wallet_zip_b64": "z"}),
    )

    secrets = ui_common._load_oracle_secrets()

    assert secrets["user"] == "ADMIN"


def test_is_connection_alive_true_when_ping_succeeds():
    assert ui_common._is_connection_alive(FakePingConnection(ping_raises=False)) is True


def test_is_connection_alive_false_when_ping_raises():
    assert ui_common._is_connection_alive(FakePingConnection(ping_raises=True)) is False


def test_get_cached_connection_reconnects_when_stale(monkeypatch):
    stale = FakePingConnection(ping_raises=True)
    fresh = FakePingConnection(ping_raises=False)
    connections = [stale, fresh]

    def fake_pooled_connection():
        return connections[0]

    fake_pooled_connection.clear = lambda: connections.pop(0)
    monkeypatch.setattr(ui_common, "_get_pooled_connection", fake_pooled_connection)

    connection = ui_common.get_cached_connection()

    assert connection is fresh
