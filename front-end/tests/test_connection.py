import base64
import io
import zipfile

from core import connection


def _make_wallet_zip_b64(files: dict) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for filename, content in files.items():
            zf.writestr(filename, content)
    return base64.b64encode(buffer.getvalue()).decode()


def test_write_wallet_from_zip_b64_extracts_files_to_dest_dir(tmp_path):
    wallet_zip_b64 = _make_wallet_zip_b64(
        {
            "cwallet.sso": b"fake-sso-bytes",
            "tnsnames.ora": b"inteligentesus_high = (description=...)",
        }
    )

    result_dir = connection.write_wallet_from_zip_b64(wallet_zip_b64, str(tmp_path / "wallet"))

    assert (tmp_path / "wallet" / "cwallet.sso").read_bytes() == b"fake-sso-bytes"
    assert (tmp_path / "wallet" / "tnsnames.ora").read_bytes() == b"inteligentesus_high = (description=...)"
    assert result_dir == str(tmp_path / "wallet")


def test_write_wallet_from_zip_b64_creates_dest_dir_if_missing(tmp_path):
    dest = tmp_path / "nested" / "wallet_dir"
    wallet_zip_b64 = _make_wallet_zip_b64({"cwallet.sso": b"x"})

    connection.write_wallet_from_zip_b64(wallet_zip_b64, str(dest))

    assert dest.is_dir()
