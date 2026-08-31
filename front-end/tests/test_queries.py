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


def test_get_indicador_capacidade_extendido_returns_rows_with_name():
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


def test_get_indicador_capacidade_extendido_sql_uses_denormalized_table():
    """MUNICIPIOS_BRASILEIROS was dropped from the data model — municipality
    names are now denormalized directly onto
    ADMIN.INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO, so this query no longer
    needs (and must not attempt) a JOIN.
    """
    description = make_description(["MUNICIPIO_CODIGO", "MUNICIPIO_NOME"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_indicador_capacidade_extendido(connection)

    sql = cursor.executed_sql[0]
    assert "INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO" in sql
    assert "JOIN" not in sql


def test_get_motivos_internacao_returns_rows():
    """MOTIVOS_INTERNACAO's column-shift bug (see git history) was fixed
    upstream by the data team — this now reads plain, correctly named
    columns, no TO_NUMBER workaround needed.
    """
    description = make_description(["CAPITULO_CID", "TOTAL_INTERNACOES", "PERMANENCIA_MEDIA_DIAS"])
    rows = [("I. Doenças infecciosas e parasitárias", 47675, 9.4)]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_motivos_internacao(connection)

    assert list(df.columns) == ["capitulo_cid", "total_internacoes", "permanencia_media_dias"]
    assert df.iloc[0]["total_internacoes"] == 47675
    assert df.iloc[0]["permanencia_media_dias"] == 9.4


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


def test_get_motivo_por_municipio_returns_rows_with_name():
    description = make_description(["CAPITULO_CID", "MUNICIPIO_CODIGO", "MUNICIPIO_NOME", "TOTAL_INTERNACOES"])
    rows = [("I. Doenças infecciosas e parasitárias", "355030", "São Paulo", 12725)]
    connection = FakeConnection([FakeCursor(description, rows)])

    df = queries.get_motivo_por_municipio(connection)

    assert df.iloc[0]["municipio_nome"] == "São Paulo"


def test_get_motivo_por_municipio_sql_uses_denormalized_table():
    """MUNICIPIOS_BRASILEIROS was dropped — MOTIVO_POR_MUNICIPIO now carries
    nome_municipio directly, so this query must not JOIN anymore."""
    description = make_description(["CAPITULO_CID", "MUNICIPIO_CODIGO", "MUNICIPIO_NOME", "TOTAL_INTERNACOES"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_motivo_por_municipio(connection)

    sql = cursor.executed_sql[0]
    assert "MOTIVO_POR_MUNICIPIO" in sql
    assert "JOIN" not in sql


def test_get_motivo_por_municipio_filters_by_capitulo():
    description = make_description(["CAPITULO_CID", "MUNICIPIO_CODIGO", "MUNICIPIO_NOME", "TOTAL_INTERNACOES"])
    cursor = FakeCursor(description, rows=[])
    connection = FakeConnection([cursor])

    queries.get_motivo_por_municipio(connection, capitulo_cid="II. Neoplasias (tumores)")

    assert cursor.executed_params[0] == {"capitulo_cid": "II. Neoplasias (tumores)"}
    assert "WHERE" in cursor.executed_sql[0]
