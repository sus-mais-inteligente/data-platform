import streamlit as st

from ui_common import apply_custom_css, apply_plotly_theme, render_sidebar_brand, render_sidebar_limitacoes

st.session_state.setdefault("welcomed", False)

st.set_page_config(
    page_title="SUS+ Inteligente",
    layout="wide",
    initial_sidebar_state="expanded" if st.session_state.welcomed else "collapsed",
)
apply_plotly_theme()
apply_custom_css()


def _render_splash() -> None:
    # Dark treatment, matching the team's presentation deck cover slide —
    # scoped to the splash only (this <style> block is only ever injected
    # while not welcomed; every other page keeps the light theme).
    st.markdown(
        """
        <style>
        [data-testid="stApp"], [data-testid="stHeader"] {
            background-color: #152D32;
        }
        [data-testid="stMainBlockContainer"] {
            min-height: 100vh;
            padding-top: 6rem !important;
            padding-bottom: 6rem !important;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }
        /* Streamlit's own wrapper around the block's contents defaults to
           flex-grow:1, which stretches it to fill the whole container above
           and leaves no leftover space for justify-content:center to
           distribute — the actual reason the splash rendered top-aligned. */
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
            flex-grow: 0;
        }
        [data-testid="stMainBlockContainer"] h1,
        [data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"],
        [data-testid="stMainBlockContainer"] [data-testid="stButton"] {
            text-align: center;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:has([data-testid="stButton"]) {
            width: 100%;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stButton"] {
            display: flex;
            justify-content: center;
        }
        .splash-wordmark {
            font-family: "Schibsted Grotesk", sans-serif;
            font-weight: 600;
            font-size: clamp(2.5rem, 6vw, 4.5rem);
            color: #FFFFFF;
            margin-bottom: 0.5rem;
        }
        .splash-wordmark .accent { color: #58C09C; }
        .splash-tagline {
            font-family: "Inter", sans-serif;
            color: #A9C4BE;
            font-size: 1.05rem;
            margin-bottom: 2.5rem;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-tertiary"] {
            color: #58C09C;
        }
        [data-testid="stMainBlockContainer"] [data-testid="stBaseButton-tertiary"]:hover {
            color: #FFFFFF;
        }
        </style>
        <div class="splash-wordmark">SUS<span class="accent">+</span> Inteligente</div>
        <div class="splash-tagline">
            Painel inteligente de acesso hospitalar
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Continuar →", type="tertiary"):
        st.session_state.welcomed = True
        st.rerun()


if not st.session_state.welcomed:
    _render_splash()
else:
    st.title("SUS+ Inteligente")
    st.markdown(
        """
Painel inteligente de acesso hospitalar e perfil de atendimento — dados do
SIH/SUS, CNES e leitos hospitalares para o estado de São Paulo, 2024.

Use o menu à esquerda para navegar entre os blocos analíticos, ou vá direto
para **Exploração em Linguagem Natural** para fazer perguntas sobre os
dados em português, sem precisar escrever SQL.

**Blocos disponíveis:**
- **Sazonalidade** — existe sazonalidade no volume de internações?
- **Indicadores de Capacidade** — quais municípios estão sob mais pressão assistencial?
- **Motivo e Permanência** — quais são os principais motivos de internação e onde se concentram?
- **Padrões e Explicabilidade** — agrupamento de municípios por perfil de pressão × capacidade, e o que mais explica a pressão assistencial
- **Exploração em Linguagem Natural** — pergunte em português, veja a resposta, a tabela de resultados e o SQL gerado (Oracle Select AI)
"""
    )
    render_sidebar_brand()
    render_sidebar_limitacoes()
