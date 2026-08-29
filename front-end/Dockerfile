FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ui_common.py ./
COPY core/ ./core/
COPY pages/ ./pages/

EXPOSE 8501

# Oracle credentials (ORACLE_USER, ORACLE_PASSWORD, ORACLE_WALLET_PASSWORD,
# ORACLE_DSN, ORACLE_WALLET_ZIP_B64) are supplied as env vars/secrets by the
# OCI Container Instance at runtime — see ui_common._load_oracle_secrets.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
