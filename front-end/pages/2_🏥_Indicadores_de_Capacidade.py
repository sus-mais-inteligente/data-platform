import plotly.express as px
import streamlit as st

from ui_common import (
    PALETTE,
    apply_plotly_theme,
    get_cached_connection,
    load_indicador_capacidade_extendido,
    render_sidebar_limitacoes,
)

st.set_page_config(page_title="Indicadores de Capacidade — SUS+ Inteligente", page_icon="🏥", layout="wide")
apply_plotly_theme()
render_sidebar_limitacoes()

st.title("🏥 Indicadores de Capacidade")
st.caption(
    "Pressão assistencial (internações por leito) por município — um indicador relativo, "
    "não uma taxa de ocupação real. Ver limitações na barra lateral."
)

conn = get_cached_connection()

with st.spinner("Carregando dados..."):
    df = load_indicador_capacidade_extendido(conn)

municipio_busca = st.selectbox(
    "Ver um município específico (opcional)",
    options=["Todos"] + sorted(df["municipio_nome"].unique()),
)
top_n = st.slider("Top N municípios no ranking", min_value=5, max_value=50, value=15)

if municipio_busca != "Todos":
    linha = df[df["municipio_nome"] == municipio_busca].iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Internações por leito", f"{linha['internacoes_por_leito']:.1f}")
    col2.metric("% leitos SUS", f"{linha['proporcao_leitos_sus'] * 100:.0f}%")
    col3.metric("Permanência média", f"{linha['permanencia_media_dias']:.1f} dias")
    col4.metric("Motivo dominante", linha["motivo_dominante"], help=f"{linha['motivo_dominante_share'] * 100:.0f}% das internações")
    st.divider()

st.subheader(f"Top {top_n} municípios em pressão assistencial")
ranking = df.nlargest(top_n, "internacoes_por_leito").sort_values("internacoes_por_leito")
fig_ranking = px.bar(
    ranking,
    x="internacoes_por_leito",
    y="municipio_nome",
    orientation="h",
    labels={"internacoes_por_leito": "Internações por leito", "municipio_nome": "Município"},
    color_discrete_sequence=[PALETTE["alerta"]],
    hover_data=["motivo_dominante", "permanencia_media_dias", "proporcao_leitos_sus"],
)
fig_ranking.update_layout(height=max(400, 28 * top_n))
st.plotly_chart(fig_ranking, use_container_width=True)

st.subheader("% de leitos que são SUS, por município")
st.caption("Quanto da capacidade instalada de cada município está de fato disponível para pacientes do SUS.")
fig_leitos_sus = px.bar(
    ranking,
    x="proporcao_leitos_sus",
    y="municipio_nome",
    orientation="h",
    labels={"proporcao_leitos_sus": "% leitos SUS", "municipio_nome": "Município"},
    color_discrete_sequence=[PALETTE["accent"]],
)
fig_leitos_sus.update_layout(xaxis_tickformat=".0%", height=max(400, 28 * top_n))
st.plotly_chart(fig_leitos_sus, use_container_width=True)

with st.expander("Ver tabela completa"):
    st.dataframe(df.sort_values("internacoes_por_leito", ascending=False), use_container_width=True)
