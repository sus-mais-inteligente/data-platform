FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui_common.py ./
COPY core/ ./core/
COPY pages/ ./pages/

EXPOSE 8080

# Port 8080 (not Streamlit's default 8501) because Cloudflare's proxy only
# forwards HTTP to a fixed allow-list of origin ports, and 8080 is on it —
# see susmaisinteligente.kxp.technology setup.
#
# Oracle credentials (ORACLE_USER, ORACLE_PASSWORD, ORACLE_WALLET_PASSWORD,
# ORACLE_DSN, ORACLE_WALLET_ZIP_B64) are supplied as env vars/secrets by the
# OCI Container Instance at runtime — see ui_common._load_oracle_secrets.
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
