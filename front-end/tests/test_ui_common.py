import os

import ui_common
from streamlit.errors import StreamlitSecretNotFoundError


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
