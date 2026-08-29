import plotly.express as px
import streamlit as st

from ui_common import (
    PALETTE,
    apply_plotly_theme,
    get_cached_connection,
    load_motivo_por_municipio,
    load_motivos_internacao,
    render_sidebar_limitacoes,
)

st.set_page_config(page_title="Motivo e Permanência — SUS Mais Inteligente", layout="wide")
apply_plotly_theme()
render_sidebar_limitacoes()

st.title("Motivo e Permanência")
st.caption("Quais são os principais motivos de internação (capítulo CID-10) e onde cada um se concentra geograficamente.")

conn = get_cached_connection()

with st.spinner("Carregando dados..."):
    df_motivos = load_motivos_internacao(conn)

st.subheader("Principais motivos de internação")
ranking_motivos = df_motivos.sort_values("total_internacoes", ascending=True)
fig_motivos = px.bar(
    ranking_motivos,
    x="total_internacoes",
    y="capitulo_cid",
    orientation="h",
    labels={"total_internacoes": "Internações", "capitulo_cid": "Capítulo CID-10"},
    color_discrete_sequence=[PALETTE["primary"]],
)
fig_motivos.update_layout(height=max(400, 28 * len(ranking_motivos)))
st.plotly_chart(fig_motivos, use_container_width=True)

st.subheader("Permanência média por motivo (estimado)")
st.caption(
    "Quais motivos resultam em internações mais longas. "
    "Este valor vem de uma coluna com definição ambígua na tabela de origem "
    "(o significado exato ainda não foi confirmado pelo time de dados) — tratar como estimativa."
)
ranking_permanencia = df_motivos.sort_values("permanencia_media_dias_aprox", ascending=True)
fig_permanencia = px.bar(
    ranking_permanencia,
    x="permanencia_media_dias_aprox",
    y="capitulo_cid",
    orientation="h",
    labels={"permanencia_media_dias_aprox": "Permanência média (dias)", "capitulo_cid": "Capítulo CID-10"},
    color_discrete_sequence=[PALETTE["accent"]],
)
fig_permanencia.update_layout(height=max(400, 28 * len(ranking_permanencia)))
st.plotly_chart(fig_permanencia, use_container_width=True)

st.divider()
st.subheader("Onde um motivo se concentra")
capitulo_escolhido = st.selectbox("Escolha um capítulo CID-10", options=sorted(df_motivos["capitulo_cid"].unique()))

with st.spinner("Carregando distribuição geográfica..."):
    df_por_municipio = load_motivo_por_municipio(conn, capitulo_cid=capitulo_escolhido)

top_municipios = df_por_municipio.nlargest(15, "total_internacoes").sort_values("total_internacoes")
fig_geografico = px.bar(
    top_municipios,
    x="total_internacoes",
    y="municipio_nome",
    orientation="h",
    labels={"total_internacoes": "Internações", "municipio_nome": "Município"},
    color_discrete_sequence=[PALETTE["neutro"]],
)
fig_geografico.update_layout(height=max(400, 28 * len(top_municipios)))
st.plotly_chart(fig_geografico, use_container_width=True)
