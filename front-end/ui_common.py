"""Streamlit-specific glue shared across pages: cached connection, Plotly
theme, and the sidebar limitations note. Deliberately outside `core/` —
`core/` stays free of Streamlit so it can be unit tested without it.
"""

from __future__ import annotations

import os

import oracledb
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from core import queries
from core.connection import get_connection

PALETTE = {
    # Extracted directly from the team's FIAP presentation deck (sampled
    # pixel colors, not eyeballed) — keeps the app's chart colors consistent
    # with the slides rather than an independently invented palette.
    "primary": "#4BA696",  # brand teal (eyebrow labels/bullets/ranking bars in the deck)
    "accent": "#377E8D",  # steel teal (the deck's own chart bar color)
    "alerta": "#C54F4C",  # coral/brick red (the deck's own chart bar color)
    "neutro": "#7B8794",
    "sequence": ["#4BA696", "#377E8D", "#C54F4C", "#7B8794", "#58C09C", "#A38B6D", "#5C6B73"],
    "sequence_continuous": ["#FAF8F4", "#387C71"],
    # Text-safe (WCAG AA, >=4.5:1 on bg) darkened variant of "primary", for
    # anywhere the brand teal is used as text/link color rather than a
    # chart fill — the deck's own #4BA696 only hits 2.75:1 on our bg.
    "primary_text": "#387C71",
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
    template.layout.font = dict(family="Inter, -apple-system, sans-serif", size=13)
    template.layout.paper_bgcolor = "rgba(0,0,0,0)"
    template.layout.plot_bgcolor = "rgba(0,0,0,0)"
    pio.templates["sus_inteligente"] = template
    pio.templates.default = "plotly_white+sus_inteligente"


def apply_custom_css() -> None:
    st.markdown(
        """
        <style>
        /* st.divider() has no dedicated data-testid, just a bare <hr> */
        [data-testid="stElementContainer"] hr {
            border: none;
            border-top: 1px solid #DEDAD1;
            margin: 2.25rem 0;
        }

        [data-testid="stHeading"] h2,
        [data-testid="stHeading"] h3 {
            margin-top: 2.5rem;
        }

        [data-testid="stMetric"] {
            padding: 1.25rem 1.5rem;
        }

        [data-testid="stBaseButton-tertiary"] {
            color: #387C71;
            font-weight: 500;
            letter-spacing: 0.01em;
        }
        [data-testid="stBaseButton-tertiary"]:hover {
            color: #24292B;
            text-decoration: underline;
        }

        .brand-mark {
            font-family: "Schibsted Grotesk", sans-serif;
            font-weight: 600;
            font-size: 0.95rem;
            letter-spacing: 0.01em;
            margin-bottom: 0.75rem;
            color: #24292B;
        }
        .brand-mark .accent { color: #387C71; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _load_oracle_secrets() -> dict:
    """Local dev reads `.streamlit/secrets.toml` (an `[oracle]` table); the
    OCI Container Instance deployment has no secrets.toml, so credentials
    arrive as env vars instead — same shape either way.

    `st.secrets` raises StreamlitSecretNotFoundError on ANY access (even a
    plain `in` check) when no secrets.toml exists anywhere on disk, rather
    than behaving like an empty container — confirmed live in the deployed
    container, which has no secrets.toml at all.
    """
    try:
        has_oracle_secrets = "oracle" in st.secrets
    except StreamlitSecretNotFoundError:
        has_oracle_secrets = False
    if has_oracle_secrets:
        return dict(st.secrets["oracle"])
    return {
        "user": os.environ["ORACLE_USER"],
        "password": os.environ["ORACLE_PASSWORD"],
        "wallet_password": os.environ["ORACLE_WALLET_PASSWORD"],
        "dsn": os.environ.get("ORACLE_DSN", "inteligentesus_high"),
        "wallet_zip_b64": os.environ["ORACLE_WALLET_ZIP_B64"],
    }


@st.cache_resource
def get_cached_connection() -> oracledb.Connection:
    return get_connection(_load_oracle_secrets())


# Cached query wrappers. The underlying Oracle gold tables only refresh once
# daily via the existing cron pipeline, so a 1-hour TTL is generous — it
# just avoids re-hitting Oracle on every widget interaction within a
# session. `_connection` (leading underscore) tells st.cache_data not to
# try to hash the connection object itself.


@st.cache_data(ttl=3600)
def load_indicador_capacidade_extendido(_connection: oracledb.Connection) -> pd.DataFrame:
    return queries.get_indicador_capacidade_extendido(_connection)


@st.cache_data(ttl=3600)
def load_motivos_internacao(_connection: oracledb.Connection) -> pd.DataFrame:
    return queries.get_motivos_internacao(_connection)


@st.cache_data(ttl=3600)
def load_motivo_por_mes(_connection: oracledb.Connection) -> pd.DataFrame:
    return queries.get_motivo_por_mes(_connection)


@st.cache_data(ttl=3600)
def load_sazonalidade_mensal(_connection: oracledb.Connection) -> pd.DataFrame:
    return queries.get_sazonalidade_mensal(_connection)


@st.cache_data(ttl=3600)
def load_motivo_por_municipio(_connection: oracledb.Connection, capitulo_cid: str | None = None) -> pd.DataFrame:
    return queries.get_motivo_por_municipio(_connection, capitulo_cid=capitulo_cid)


def render_sidebar_limitacoes() -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand-mark">SUS<span class="accent">+</span> Inteligente</div>',
            unsafe_allow_html=True,
        )
        st.markdown("---")
        with st.expander("Limitações dos dados"):
            st.markdown(LIMITACOES_TEXTO)
