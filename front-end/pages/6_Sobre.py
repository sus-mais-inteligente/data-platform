import streamlit as st

from ui_common import apply_custom_css, apply_plotly_theme, render_sidebar_limitacoes

st.set_page_config(page_title="Sobre — SUS+ Inteligente", page_icon="🏥", layout="wide")
apply_plotly_theme()
apply_custom_css()
render_sidebar_limitacoes()

st.title("Sobre")

st.markdown(
    """
Este é o resultado de um projeto para o **Enterprise Challenge da FIAP** —
**Grupo 51** (Turma 1TSCO), em parceria com a Oracle.

**Equipe:**
- Renata Cristina de Oliveira — RM 569564 — rm569564@fiap.com.br
- Guilherme Francisco — RM 569145 — rm569145@fiap.com.br
- Rafael Canto Xavier — RM 572513 — rm572513@fiap.com.br

**Segundo Semestre / 2026**
"""
)
