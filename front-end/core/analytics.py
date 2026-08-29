"""Clustering and explicabilidade analytics — ported from eda_modelagem.py's
estabelecimento-level KMeans/RandomForest logic, adapted to município-level
columns (Oracle only exposes indicadores at município granularity, not
estabelecimento). No Streamlit calls here.
"""

from __future__ import annotations

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

CLUSTER_FEATURES = ["internacoes_por_leito", "leitos_existentes_total", "permanencia_media_dias"]

# Clusters are always ranked by mean internacoes_por_leito, descending —
# index 0 is always the highest-pressure group regardless of KMeans' own
# arbitrary cluster numbering.
CLUSTER_PROFILE_NAMES = [
    "Alta pressão (candidato a enviar pacientes)",
    "Equilibrado",
    "Capacidade ociosa (pode receber pacientes)",
]

EXPLICABILIDADE_FEATURES = [
    "permanencia_media_dias",
    "estabelecimentos_distintos",
    "proporcao_leitos_sus",
    "motivo_dominante_share",
]

# leitos-derived columns are deliberately excluded from EXPLICABILIDADE_FEATURES:
# pressão assistencial (the target) is internações / leitos, so leitos would be
# circular as an explanatory variable.
EXPLICABILIDADE_LABELS_PT = {
    "permanencia_media_dias": "Permanência média (dias)",
    "estabelecimentos_distintos": "Nº de estabelecimentos distintos (diversidade da rede local)",
    "proporcao_leitos_sus": "% dos leitos que são SUS (vs. particular/convênio)",
    "motivo_dominante_share": "Concentração num motivo principal (% das internações no motivo mais comum)",
}


def cluster_municipios(df: pd.DataFrame, n_clusters: int = 3, random_state: int = 42) -> pd.DataFrame:
    """Cluster municípios by pressão assistencial x capacidade x permanência.

    Returns a copy of `df` (rows missing any cluster feature are dropped)
    with two new columns: `cluster` (raw KMeans label) and `perfil`
    (the human-readable pt-BR profile name, ranked by mean pressão).
    """
    working = df.dropna(subset=CLUSTER_FEATURES).copy()
    X = working[CLUSTER_FEATURES].fillna(0)
    X_scaled = StandardScaler().fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=random_state, n_init=10)
    working["cluster"] = kmeans.fit_predict(X_scaled)

    ordem_clusters = (
        working.groupby("cluster")["internacoes_por_leito"].mean().sort_values(ascending=False).index
    )
    nomes_cluster = {
        cluster_id: CLUSTER_PROFILE_NAMES[i] if i < len(CLUSTER_PROFILE_NAMES) else f"Grupo {i + 1}"
        for i, cluster_id in enumerate(ordem_clusters)
    }
    working["perfil"] = working["cluster"].map(nomes_cluster)
    return working


def explicabilidade_modelo(df: pd.DataFrame, test_size: float = 0.2, random_state: int = 42) -> dict:
    """RandomForest explaining pressão assistencial (internações por leito)
    from non-circular município-level features.

    Returns {"r2": float, "mae": float, "importancias": pd.Series,
    "direcao": pd.Series, "labels_pt": dict}. `direcao` is each feature's
    correlation with the target — positive means the feature pushes pressão
    up, matching eda_modelagem.py's approach to showing effect direction
    alongside raw importance.
    """
    working = df.dropna(subset=EXPLICABILIDADE_FEATURES + ["internacoes_por_leito"]).copy()
    X = working[EXPLICABILIDADE_FEATURES].fillna(0)
    y = working["internacoes_por_leito"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state)
    modelo = RandomForestRegressor(n_estimators=200, random_state=random_state, max_depth=6)
    modelo.fit(X_train, y_train)
    y_pred = modelo.predict(X_test)

    importancias = pd.Series(modelo.feature_importances_, index=EXPLICABILIDADE_FEATURES).sort_values(
        ascending=False
    )
    direcao = X.corrwith(y).reindex(importancias.index)

    return {
        "r2": r2_score(y_test, y_pred),
        "mae": mean_absolute_error(y_test, y_pred),
        "importancias": importancias,
        "direcao": direcao,
        "labels_pt": EXPLICABILIDADE_LABELS_PT,
    }
