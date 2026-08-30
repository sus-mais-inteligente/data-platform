import streamlit as st

from core.select_ai import ask_select_ai
from ui_common import apply_custom_css, apply_plotly_theme, get_cached_connection, render_sidebar_brand, render_sidebar_limitacoes

st.set_page_config(page_title="Exploração NL — SUS+ Inteligente", layout="wide")
apply_plotly_theme()
apply_custom_css()
render_sidebar_brand()
render_sidebar_limitacoes()

st.title("Exploração em Linguagem Natural")
st.caption(
    "Pergunte sobre os dados de internação em português — sem precisar escrever SQL. "
    "Powered by Oracle Select AI, restrito às tabelas de indicadores deste projeto."
)

EXEMPLOS = [
    "Quais municípios têm mais internações por leito?",
    "Qual o motivo de internação mais comum?",
    "Quantas internações houve em cada mês?",
    "Quais municípios têm a maior proporção de leitos SUS?",
]

with st.expander("Exemplos de perguntas"):
    for exemplo in EXEMPLOS:
        st.markdown(f"- {exemplo}")

conn = get_cached_connection()

pergunta = st.text_input("Sua pergunta", placeholder="Ex.: Quais municípios têm mais internações por leito?")

if st.button("Perguntar", type="primary", disabled=not pergunta):
    with st.spinner("Consultando Select AI..."):
        try:
            resultado = ask_select_ai(conn, pergunta)
        except Exception as exc:
            st.error(f"Não foi possível obter uma resposta: {exc}")
        else:
            st.markdown("### Resposta")
            st.markdown(resultado["answer"])

            st.markdown("### Resultado")
            if resultado["rows"].empty:
                st.info("Nenhuma linha retornada para essa pergunta.")
            else:
                st.dataframe(resultado["rows"], use_container_width=True, hide_index=True)

            with st.expander("Ver SQL gerado"):
                st.code(resultado["sql"], language="sql")
