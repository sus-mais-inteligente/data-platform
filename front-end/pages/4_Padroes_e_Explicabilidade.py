import plotly.express as px
import streamlit as st

from core.analytics import cluster_municipios, explicabilidade_modelo
from ui_common import (
    PALETTE,
    apply_custom_css,
    apply_plotly_theme,
    get_cached_connection,
    load_indicador_capacidade_extendido,
    render_sidebar_brand,
    render_sidebar_limitacoes,
)

st.set_page_config(page_title="Padrões e Explicabilidade — SUS+ Inteligente", layout="wide")
apply_plotly_theme()
apply_custom_css()
render_sidebar_brand()
render_sidebar_limitacoes()

st.title("Padrões e Explicabilidade")
st.caption(
    "Agrupamento de municípios por perfil de pressão × capacidade, e o que mais está "
    "associado à pressão assistencial — não é previsão (forecasting), é associação no presente."
)

conn = get_cached_connection()

with st.spinner("Carregando dados..."):
    df = load_indicador_capacidade_extendido(conn)

st.subheader("Agrupamento: pressão × capacidade × permanência")
n_clusters = st.slider("Número de grupos", min_value=2, max_value=6, value=3)

with st.spinner("Calculando agrupamento..."):
    clustered = cluster_municipios(df, n_clusters=n_clusters)

fig_cluster = px.scatter(
    clustered,
    x="leitos_existentes_total",
    y="internacoes_por_leito",
    color="perfil",
    size="permanencia_media_dias",
    hover_name="municipio_nome",
    labels={
        "leitos_existentes_total": "Leitos existentes",
        "internacoes_por_leito": "Internações por leito (pressão)",
        "perfil": "Perfil",
    },
    # Explicit mapping, not just a color sequence + implicit row order:
    # alta pressão is the worse state (worth flagging), so it gets the
    # alert color; capacidade ociosa is comparatively fine, so it gets the
    # calm brand teal. Any extra "Grupo N" profile (n_clusters > 3) falls
    # back to color_discrete_sequence.
    color_discrete_map={
        "Alta pressão (candidato a enviar pacientes)": PALETTE["alerta"],
        "Equilibrado": PALETTE["neutro"],
        "Capacidade ociosa (pode receber pacientes)": PALETTE["primary"],
    },
    color_discrete_sequence=PALETTE["sequence"],
)
st.plotly_chart(fig_cluster, use_container_width=True)

col_enviar, col_receber = st.columns(2)
with col_enviar:
    st.markdown("**Candidatos a enviar pacientes** (alta pressão)")
    alta_pressao = clustered[clustered["perfil"].str.contains("enviar", case=False)]
    st.dataframe(
        alta_pressao.nlargest(8, "internacoes_por_leito")[["municipio_nome", "internacoes_por_leito", "leitos_existentes_total"]],
        use_container_width=True,
        hide_index=True,
    )
with col_receber:
    st.markdown("**Candidatos a receber pacientes** (capacidade ociosa)")
    ociosa = clustered[clustered["perfil"].str.contains("receber", case=False)]
    st.dataframe(
        ociosa.nsmallest(8, "internacoes_por_leito")[["municipio_nome", "internacoes_por_leito", "leitos_existentes_total"]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("Explicabilidade: o que mais explica a pressão assistencial")

with st.spinner("Treinando modelo..."):
    resultado = explicabilidade_modelo(df)

st.metric("R² (variação explicada)", f"{resultado['r2'] * 100:.0f}%", border=True)
st.caption(
    "O modelo explica uma parte da variação da pressão assistencial entre municípios usando "
    "variáveis que não fazem parte do próprio cálculo do indicador (leitos foi propositalmente excluído: "
    "seria circular, já que pressão = internações ÷ leitos)."
)

importancias = resultado["importancias"]
direcao = resultado["direcao"]
labels_pt = resultado["labels_pt"]

cores = [PALETTE["alerta"] if direcao[f] > 0 else PALETTE["accent"] for f in importancias.index]
fig_importancia = px.bar(
    x=importancias.values,
    y=[labels_pt.get(f, f) for f in importancias.index],
    orientation="h",
    labels={"x": "Importância relativa", "y": ""},
    color=[("Aumenta a pressão" if direcao[f] > 0 else "Reduz a pressão") for f in importancias.index],
    color_discrete_map={"Aumenta a pressão": PALETTE["alerta"], "Reduz a pressão": PALETTE["accent"]},
)
fig_importancia.update_layout(yaxis=dict(categoryorder="total ascending"), legend_title="")
st.plotly_chart(fig_importancia, use_container_width=True)
