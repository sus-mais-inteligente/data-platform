import streamlit as st

from ui_common import apply_plotly_theme, render_sidebar_limitacoes

st.set_page_config(page_title="SUS Mais Inteligente", layout="wide")
apply_plotly_theme()

st.title("SUS Mais Inteligente")
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

render_sidebar_limitacoes()
