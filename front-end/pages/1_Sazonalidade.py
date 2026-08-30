import plotly.express as px
import streamlit as st

from ui_common import (
    PALETTE,
    apply_custom_css,
    apply_plotly_theme,
    get_cached_connection,
    load_motivo_por_mes,
    load_sazonalidade_mensal,
    render_sidebar_limitacoes,
)

MES_NOMES = {
    "01": "Janeiro",
    "02": "Fevereiro",
    "03": "Março",
    "04": "Abril",
    "05": "Maio",
    "06": "Junho",
    "07": "Julho",
    "08": "Agosto",
    "09": "Setembro",
    "10": "Outubro",
    "11": "Novembro",
    "12": "Dezembro",
}

st.set_page_config(page_title="Sazonalidade — SUS+ Inteligente", page_icon="🏥", layout="wide")
apply_plotly_theme()
apply_custom_css()
render_sidebar_limitacoes()

st.title("Sazonalidade")
st.caption(
    "Existe sazonalidade no volume de internações ao longo do ano? "
    "Cobertura: fevereiro, junho, agosto e dezembro de 2024 (únicos meses disponíveis na fonte)."
)

conn = get_cached_connection()

with st.spinner("Carregando dados..."):
    df_mensal = load_sazonalidade_mensal(conn)
    df_por_motivo = load_motivo_por_mes(conn)

st.subheader("Volume total de internações por mês")
df_mensal = df_mensal.assign(mes_nome=df_mensal["mes_competencia"].map(MES_NOMES))
fig_mensal = px.bar(
    df_mensal,
    x="mes_nome",
    y="total_internacoes",
    labels={"mes_nome": "Mês", "total_internacoes": "Internações"},
    color_discrete_sequence=[PALETTE["primary"]],
)
fig_mensal.update_xaxes(categoryorder="array", categoryarray=df_mensal["mes_nome"].tolist())
st.plotly_chart(fig_mensal, use_container_width=True)

st.subheader("Sazonalidade por motivo (capítulo CID-10)")
st.caption("Nem todo motivo de internação segue o mesmo padrão sazonal — o heatmap mostra onde cada um concentra volume.")

capitulos_disponiveis = sorted(df_por_motivo["capitulo_cid"].unique())
capitulos_selecionados = st.multiselect(
    "Filtrar capítulos CID-10",
    options=capitulos_disponiveis,
    default=capitulos_disponiveis,
)
df_heatmap = df_por_motivo[df_por_motivo["capitulo_cid"].isin(capitulos_selecionados)].copy()
df_heatmap["mes_nome"] = df_heatmap["mes_competencia"].map(MES_NOMES)

pivot = df_heatmap.pivot(index="capitulo_cid", columns="mes_nome", values="total_internacoes")
meses_presentes = [nome for codigo, nome in MES_NOMES.items() if nome in pivot.columns]
pivot = pivot[meses_presentes]
fig_heatmap = px.imshow(
    pivot,
    labels={"x": "Mês", "y": "Capítulo CID-10", "color": "Internações"},
    color_continuous_scale=PALETTE["sequence_continuous"],
    aspect="auto",
)
fig_heatmap.update_layout(height=max(400, 28 * len(pivot)))
st.plotly_chart(fig_heatmap, use_container_width=True)
