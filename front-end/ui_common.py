"""Streamlit-specific glue shared across pages: cached connection, Plotly
theme, and the sidebar limitations note. Deliberately outside `core/` —
`core/` stays free of Streamlit so it can be unit tested without it.
"""

import os

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from core import queries
from core.connection import get_connection

PALETTE = {
    "primary": "#0B5FA5",
    "accent": "#00A896",
    "alerta": "#D64545",
    "neutro": "#7B8794",
    "sequence": ["#0B5FA5", "#00A896", "#F4A261", "#D64545", "#7B2CBF", "#2A9D8F", "#5C6B73"],
}

LIMITACOES_TEXTO = """
- **Cobertura**: São Paulo, 2024 — apenas 4 dos 12 meses (fev/jun/ago/dez) têm dado de internação disponível na fonte. 2025 ainda não foi publicado pelo DATASUS.
- **"Internações por leito"** é um indicador *relativo* de pressão assistencial entre municípios, não uma taxa de ocupação real.
- O bloco de **explicabilidade** mostra o que está associado à pressão assistencial hoje — não é previsão (forecasting).
- Indicadores normalizados por população (internações por 1.000 habitantes) ainda não estão disponíveis nesta versão.
"""


def apply_plotly_theme() -> None:
    template = go.layout.Template()
    template.layout.colorway = PALETTE["sequence"]
    template.layout.font = dict(family="-apple-system, Segoe UI, sans-serif", size=13)
    template.layout.paper_bgcolor = "rgba(0,0,0,0)"
    template.layout.plot_bgcolor = "rgba(0,0,0,0)"
    pio.templates["sus_inteligente"] = template
    pio.templates.default = "plotly_white+sus_inteligente"


def _load_oracle_secrets() -> dict:
    """Local dev reads `.streamlit/secrets.toml` (an `[oracle]` table); the
    OCI Container Instance deployment has no secrets.toml, so credentials
    arrive as env vars instead — same shape either way.
    """
    if "oracle" in st.secrets:
        return dict(st.secrets["oracle"])
    return {
        "user": os.environ["ORACLE_USER"],
        "password": os.environ["ORACLE_PASSWORD"],
        "wallet_password": os.environ["ORACLE_WALLET_PASSWORD"],
        "dsn": os.environ.get("ORACLE_DSN", "inteligentesus_high"),
        "wallet_zip_b64": os.environ["ORACLE_WALLET_ZIP_B64"],
    }


@st.cache_resource
def get_cached_connection():
    return get_connection(_load_oracle_secrets())


# Cached query wrappers. The underlying Oracle gold tables only refresh once
# daily via the existing cron pipeline, so a 1-hour TTL is generous — it
# just avoids re-hitting Oracle on every widget interaction within a
# session. `_connection` (leading underscore) tells st.cache_data not to
# try to hash the connection object itself.


@st.cache_data(ttl=3600)
def load_indicador_capacidade_extendido(_connection):
    return queries.get_indicador_capacidade_extendido(_connection)


@st.cache_data(ttl=3600)
def load_motivos_internacao(_connection):
    return queries.get_motivos_internacao(_connection)


@st.cache_data(ttl=3600)
def load_motivo_por_mes(_connection):
    return queries.get_motivo_por_mes(_connection)


@st.cache_data(ttl=3600)
def load_sazonalidade_mensal(_connection):
    return queries.get_sazonalidade_mensal(_connection)


@st.cache_data(ttl=3600)
def load_motivo_por_municipio(_connection, capitulo_cid=None):
    return queries.get_motivo_por_municipio(_connection, capitulo_cid=capitulo_cid)


def render_sidebar_limitacoes() -> None:
    with st.sidebar:
        st.markdown("---")
        with st.expander("⚠️ Limitações dos dados"):
            st.markdown(LIMITACOES_TEXTO)
