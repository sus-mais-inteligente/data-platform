"""Oracle Autonomous Database connection setup.

`write_wallet_from_zip_b64` is pure and unit-tested. `get_connection` is a
thin wrapper around `oracledb.connect` — not unit tested, same convention as
the rest of this codebase (no live-DB assertions in the test suite).
"""

from __future__ import annotations

import base64
import io
import tempfile
import zipfile
from pathlib import Path

import oracledb


def write_wallet_from_zip_b64(wallet_zip_b64: str, dest_dir: str) -> str:
    """Decode a base64-encoded Oracle wallet .zip and extract it into
    dest_dir. Returns dest_dir.

    The wallet is delivered as a single base64 string (of the whole .zip),
    both in local `.streamlit/secrets.toml` and as the OCI Container
    Instance's env var — same shape in both places, decoded the same way.
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    zip_bytes = base64.b64decode(wallet_zip_b64)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(dest)
    return str(dest)


def get_connection(secrets: dict) -> oracledb.Connection:
    """Build a live Oracle connection from a secrets mapping.

    Expected shape of `secrets`:
      {
        "user": "...",
        "password": "...",
        "wallet_password": "...",
        "dsn": "inteligentesus_high",
        "wallet_zip_b64": "<base64 of the whole wallet .zip>",
      }
    """
    wallet_dir = write_wallet_from_zip_b64(secrets["wallet_zip_b64"], tempfile.mkdtemp(prefix="oracle_wallet_"))
    return oracledb.connect(
        user=secrets["user"],
        password=secrets["password"],
        dsn=secrets["dsn"],
        config_dir=wallet_dir,
        wallet_location=wallet_dir,
        wallet_password=secrets["wallet_password"],
    )
