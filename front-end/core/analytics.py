"""Clusterização e explicabilidade — portado da lógica KMeans/RandomForest
por estabelecimento do eda_modelagem.py, adaptado pras colunas em nível de
município (o Oracle só expõe indicadores por município, não por
estabelecimento). Nenhuma chamada Streamlit aqui.
"""

from __future__ import annotations

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

CLUSTER_FEATURES = ["internacoes_por_leito", "leitos_existentes_total", "permanencia_media_dias"]

# Os clusters são sempre ranqueados pela média de internacoes_por_leito, em
# ordem decrescente — o índice 0 é sempre o grupo de maior pressão,
# independente da numeração arbitrária que o próprio KMeans atribui.
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

# Colunas derivadas de leitos são propositalmente excluídas de
# EXPLICABILIDADE_FEATURES: a pressão assistencial (o alvo) é
# internações / leitos, então leitos seria circular como variável
# explicativa.
EXPLICABILIDADE_LABELS_PT = {
    "permanencia_media_dias": "Permanência média (dias)",
    "estabelecimentos_distintos": "Nº de estabelecimentos distintos (diversidade da rede local)",
    "proporcao_leitos_sus": "% dos leitos que são SUS (vs. particular/convênio)",
    "motivo_dominante_share": "Concentração num motivo principal (% das internações no motivo mais comum)",
}


def cluster_municipios(df: pd.DataFrame, n_clusters: int = 3, random_state: int = 42) -> pd.DataFrame:
    """Agrupa municípios por pressão assistencial x capacidade x permanência.

    Devolve uma cópia de `df` (linhas sem alguma feature de cluster são
    descartadas) com duas colunas novas: `cluster` (rótulo bruto do KMeans)
    e `perfil` (o nome do perfil em pt-BR, legível, ranqueado pela pressão média).
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
    """RandomForest explicando a pressão assistencial (internações por leito)
    a partir de features não circulares, em nível de município.

    Devolve {"r2": float, "mae": float, "importancias": pd.Series,
    "direcao": pd.Series, "labels_pt": dict}. `direcao` é a correlação de
    cada feature com o alvo — positiva significa que a feature empurra a
    pressão pra cima, seguindo a mesma abordagem do eda_modelagem.py de
    mostrar a direção do efeito junto com a importância bruta.
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
