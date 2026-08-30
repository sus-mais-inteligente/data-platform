FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui_common.py ./
COPY core/ ./core/
COPY pages/ ./pages/
COPY .streamlit/config.toml ./.streamlit/config.toml

EXPOSE 80

# Port 80 (not Streamlit's default 8501): Cloudflare's proxy connects to
# the origin on port 80 for HTTP by default — anything else needs an
# explicit Origin Rule on the Cloudflare side. Using 80 needs zero extra
# Cloudflare config. Container runs as root (no USER set), so binding to
# this privileged port works fine.
#
# Oracle credentials (ORACLE_USER, ORACLE_PASSWORD, ORACLE_WALLET_PASSWORD,
# ORACLE_DSN, ORACLE_WALLET_ZIP_B64) are supplied as env vars/secrets by the
# OCI Container Instance at runtime — see ui_common._load_oracle_secrets.
CMD ["streamlit", "run", "app.py", "--server.port=80", "--server.address=0.0.0.0", "--server.headless=true"]
