import numpy as np
import pandas as pd

from core import analytics


def _synthetic_municipios(n_per_group=15, seed=0):
    rng = np.random.default_rng(seed)
    groups = []
    # alta pressão: poucos leitos, muita internação, permanência curta
    groups.append(
        pd.DataFrame(
            {
                "internacoes_por_leito": rng.normal(30, 2, n_per_group),
                "leitos_existentes_total": rng.normal(15, 2, n_per_group),
                "permanencia_media_dias": rng.normal(2, 0.3, n_per_group),
            }
        )
    )
    # equilibrado
    groups.append(
        pd.DataFrame(
            {
                "internacoes_por_leito": rng.normal(15, 2, n_per_group),
                "leitos_existentes_total": rng.normal(40, 3, n_per_group),
                "permanencia_media_dias": rng.normal(4, 0.3, n_per_group),
            }
        )
    )
    # capacidade ociosa: muitos leitos, pouca internação relativa
    groups.append(
        pd.DataFrame(
            {
                "internacoes_por_leito": rng.normal(3, 1, n_per_group),
                "leitos_existentes_total": rng.normal(80, 5, n_per_group),
                "permanencia_media_dias": rng.normal(6, 0.5, n_per_group),
            }
        )
    )
    return pd.concat(groups, ignore_index=True)


def test_cluster_municipios_labels_highest_pressao_group():
    df = _synthetic_municipios()

    result = analytics.cluster_municipios(df, n_clusters=3)

    assert set(result["perfil"].unique()) == {
        "Alta pressão (candidato a enviar pacientes)",
        "Equilibrado",
        "Capacidade ociosa (pode receber pacientes)",
    }
    # the group with the highest internacoes_por_leito must be labeled "alta pressão"
    highest_pressao_rows = result.nlargest(5, "internacoes_por_leito")
    assert (highest_pressao_rows["perfil"] == "Alta pressão (candidato a enviar pacientes)").all()

    lowest_pressao_rows = result.nsmallest(5, "internacoes_por_leito")
    assert (lowest_pressao_rows["perfil"] == "Capacidade ociosa (pode receber pacientes)").all()


def test_cluster_municipios_drops_rows_missing_features():
    df = _synthetic_municipios(n_per_group=5)
    df.loc[0, "permanencia_media_dias"] = None

    result = analytics.cluster_municipios(df, n_clusters=3)

    assert len(result) == len(df) - 1


def _synthetic_explicabilidade(n=60, seed=1):
    rng = np.random.default_rng(seed)
    motivo_dominante_share = rng.uniform(0.1, 0.9, n)
    # internacoes_por_leito is deliberately driven mostly by motivo_dominante_share,
    # so the model should pick that out as the most important feature
    internacoes_por_leito = 5 + motivo_dominante_share * 40 + rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "permanencia_media_dias": rng.normal(4, 1, n),
            "estabelecimentos_distintos": rng.integers(1, 5, n),
            "proporcao_leitos_sus": rng.uniform(0.5, 1.0, n),
            "motivo_dominante_share": motivo_dominante_share,
            "internacoes_por_leito": internacoes_por_leito,
        }
    )


def test_explicabilidade_modelo_returns_expected_shape():
    df = _synthetic_explicabilidade()

    result = analytics.explicabilidade_modelo(df)

    assert isinstance(result["r2"], float)
    assert set(result["importancias"].index) == set(analytics.EXPLICABILIDADE_FEATURES)
    assert abs(result["importancias"].sum() - 1.0) < 1e-6
    assert set(result["direcao"].index) == set(analytics.EXPLICABILIDADE_FEATURES)


def test_explicabilidade_modelo_identifies_dominant_driver():
    df = _synthetic_explicabilidade()

    result = analytics.explicabilidade_modelo(df)

    assert result["importancias"].idxmax() == "motivo_dominante_share"
    assert result["direcao"]["motivo_dominante_share"] > 0
