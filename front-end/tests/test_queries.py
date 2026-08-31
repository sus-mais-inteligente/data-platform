from core import queries
from tests.fakes import FakeConnection, FakeCursor, make_description


def test_rows_to_df_lowercases_columns():
    cursor = FakeCursor(
        description=make_description(["MUNICIPIO_CODIGO", "TOTAL_INTERNACOES"]),
        rows=[("350100", 656)],
    )
    df = queries._rows_to_df(cursor)
    assert list(df.columns) == ["municipio_codigo", "total_internacoes"]
    assert df.iloc[0]["total_internacoes"] == 656


def test_get_indicador_capacidade_extendido_returns_joined_rows():
    description = make_description(
        [
            "MUNICIPIO_CODIGO",
            "MUNICIPIO_NOME",
            "TOTAL_INTERNACOES",
            "PERMANENCIA_MEDIA_DIAS",
            "ESTABELECIMENTOS_DISTINTOS",
            "LEITOS_EXISTENTES_TOTAL",
            "LEITOS_SUS_TOTAL",
            "INTERNACOES_POR_LEITO",
            "PROPORCAO_LEITOS_SUS",
            "MOTIVO_DOMINANTE",
            "MOTIVO_DOMINANTE_SHARE",
        ]
    )
    rows = [
        (
            "350100",
            "Altinópolis",
            656,
            1.9,
            1,
            21,
            19,
            31.24,
            0.905,
            "XIX. Lesões e envenenamentos (causas externas)",
            0.323,
        )
    ]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_indicador_capacidade_extendido(connection)

    assert list(df["municipio_nome"]) == ["Altinópolis"]
    assert df.iloc[0]["internacoes_por_leito"] == 31.24
    assert df.iloc[0]["motivo_dominante"] == "XIX. Lesões e envenenamentos (causas externas)"


def test_get_indicador_capacidade_extendido_sql_joins_municipio_names():
    description = make_description(["MUNICIPIO_CODIGO", "MUNICIPIO_NOME"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_indicador_capacidade_extendido(connection)

    sql = cursor.executed_sql[0]
    assert "INDICADOR_CAPACIDADE_EXTENDIDO" in sql
    assert "MUNICIPIOS_BRASILEIROS" in sql


def test_get_motivos_internacao_applies_column_workaround():
    """MOTIVOS_INTERNACAO's External Table definition has shifted columns:
    the column named MUNICIPIO_CODIGO actually holds total_internacoes, and
    the column named TOTAL_INTERNACOES actually holds an average (likely
    permanencia_media_dias). Verified by cross-checking against MOTIVO_POR_MES
    (whose sums match the mislabeled MUNICIPIO_CODIGO column exactly).
    """
    # description reflects the SQL's AS aliases, which is what a real
    # cursor.description returns post-query — not the source column names.
    description = make_description(["CAPITULO_CID", "TOTAL_INTERNACOES", "PERMANENCIA_MEDIA_DIAS_APROX"])
    rows = [("I. Doenças infecciosas e parasitárias", 47675, 9.4)]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_motivos_internacao(connection)

    assert list(df.columns) == ["capitulo_cid", "total_internacoes", "permanencia_media_dias_aprox"]
    assert df.iloc[0]["total_internacoes"] == 47675
    assert df.iloc[0]["permanencia_media_dias_aprox"] == 9.4


def test_get_motivos_internacao_casts_total_internacoes_to_number():
    """MUNICIPIO_CODIGO (the mislabeled source column) is VARCHAR2 in Oracle,
    so without an explicit TO_NUMBER cast in the query, the real
    total_internacoes count comes back as a string — which sorts
    lexicographically instead of numerically in any chart built on top of
    it. Caught via a live app screenshot, not by the mocked tests above
    (a fake cursor can't reproduce Oracle's own column typing) — so this
    test checks the query casts explicitly rather than re-mocking the bug.
    """
    description = make_description(["CAPITULO_CID", "TOTAL_INTERNACOES", "PERMANENCIA_MEDIA_DIAS_APROX"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_motivos_internacao(connection)

    assert "TO_NUMBER(municipio_codigo)" in cursor.executed_sql[0]


def test_get_motivo_por_mes_returns_rows():
    description = make_description(["CAPITULO_CID", "MES_COMPETENCIA", "TOTAL_INTERNACOES"])
    rows = [
        ("I. Doenças infecciosas e parasitárias", "02", 11114),
        ("I. Doenças infecciosas e parasitárias", "06", 13888),
    ]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_motivo_por_mes(connection)

    assert len(df) == 2
    assert df.iloc[0]["mes_competencia"] == "02"


def test_get_sazonalidade_mensal_aggregates_across_motivos():
    description = make_description(["CAPITULO_CID", "MES_COMPETENCIA", "TOTAL_INTERNACOES"])
    rows = [
        ("I. Doenças infecciosas e parasitárias", "02", 100),
        ("II. Neoplasias (tumores)", "02", 50),
        ("I. Doenças infecciosas e parasitárias", "06", 200),
    ]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_sazonalidade_mensal(connection)

    result = dict(zip(df["mes_competencia"], df["total_internacoes"]))
    assert result == {"02": 150, "06": 200}


def test_get_motivo_por_municipio_joins_municipio_names():
    description = make_description(["CAPITULO_CID", "MUNICIPIO_CODIGO", "MUNICIPIO_NOME", "TOTAL_INTERNACOES"])
    rows = [("I. Doenças infecciosas e parasitárias", "355030", "São Paulo", 12725)]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_motivo_por_municipio(connection)

    assert df.iloc[0]["municipio_nome"] == "São Paulo"


def test_get_motivo_por_municipio_filters_by_capitulo():
    description = make_description(["CAPITULO_CID", "MUNICIPIO_CODIGO", "MUNICIPIO_NOME", "TOTAL_INTERNACOES"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_motivo_por_municipio(connection, capitulo_cid="II. Neoplasias (tumores)")

    assert cursor.executed_params[0] == {"capitulo_cid": "II. Neoplasias (tumores)"}
    assert "WHERE" in cursor.executed_sql[0]
