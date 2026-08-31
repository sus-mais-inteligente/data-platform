"""Funções de acesso a dados no Oracle. Cada função recebe uma connection
viva e devolve um DataFrame pandas — nenhuma chamada Streamlit neste módulo,
para poder ser testada com uma connection/cursor fake.
"""

from __future__ import annotations

import pandas as pd


def _rows_to_df(cursor) -> pd.DataFrame:
    columns = [col[0].lower() for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def get_indicador_capacidade_extendido(connection) -> pd.DataFrame:
    """Indicador de capacidade por município, com motivo dominante e
    proporção de leitos SUS, já com o nome do município via JOIN.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            i.municipio_codigo,
            m.nome AS municipio_nome,
            i.total_internacoes,
            i.permanencia_media_dias,
            i.estabelecimentos_distintos,
            i.leitos_existentes_total,
            i.leitos_sus_total,
            i.internacoes_por_leito,
            i.proporcao_leitos_sus,
            i.motivo_dominante,
            i.motivo_dominante_share
        FROM ADMIN.INDICADOR_CAPACIDADE_EXTENDIDO i
        JOIN ADMIN.MUNICIPIOS_BRASILEIROS m
            ON SUBSTR(m.codigo_ibge, 1, 6) = i.municipio_codigo
        ORDER BY i.internacoes_por_leito DESC
        """
    )
    return _rows_to_df(cursor)


def get_motivos_internacao(connection) -> pd.DataFrame:
    """Ranking geral dos capítulos CID-10 por volume.

    WORKAROUND: a External Table ADMIN.MOTIVOS_INTERNACAO tem o column_list
    deslocado — a coluna chamada MUNICIPIO_CODIGO na verdade guarda o
    total_internacoes real, e a coluna chamada TOTAL_INTERNACOES guarda um
    decimal pequeno (provavelmente permanencia_media_dias), não um código de
    município nem um total. Confirmado cruzando as somas com MOTIVO_POR_MES,
    que está corretamente rotulada. Aqui os nomes são realiasados pro
    significado real, em vez de corrigir na fonte, por decisão de produto —
    sinalizado pro time como bug de plataforma de dados a corrigir no DDL da
    External Table.

    MUNICIPIO_CODIGO é declarada VARCHAR2 (é feita pra guardar código como
    texto), então o total real que está armazenado ali volta como string sem
    um cast explícito — o TO_NUMBER evita que essa contagem seja ordenada
    como texto (lexicograficamente) em vez de numericamente em qualquer
    gráfico que a use.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            capitulo_cid,
            TO_NUMBER(municipio_codigo) AS total_internacoes,
            total_internacoes AS permanencia_media_dias_aprox
        FROM ADMIN.MOTIVOS_INTERNACAO
        ORDER BY TO_NUMBER(municipio_codigo) DESC
        """
    )
    return _rows_to_df(cursor)


def get_motivo_por_mes(connection) -> pd.DataFrame:
    """Internações por capítulo CID-10 e mês (usado no heatmap de sazonalidade)."""
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT capitulo_cid, mes_competencia, total_internacoes
        FROM ADMIN.MOTIVO_POR_MES
        ORDER BY mes_competencia, capitulo_cid
        """
    )
    return _rows_to_df(cursor)


def get_sazonalidade_mensal(connection) -> pd.DataFrame:
    """Volume mensal total de internações, derivado somando MOTIVO_POR_MES
    entre os capítulos — não existe tabela dedicada pra isso no Oracle.
    """
    df = get_motivo_por_mes(connection)
    result = (
        df.groupby("mes_competencia", as_index=False)["total_internacoes"]
        .sum()
        .sort_values("mes_competencia")
        .reset_index(drop=True)
    )
    return result


def get_motivo_por_municipio(connection, capitulo_cid: str | None = None) -> pd.DataFrame:
    """Internações por capítulo CID-10 e município, com nome do município via JOIN.

    Passe capitulo_cid pra filtrar por um único capítulo (ex.: pra uma visão
    de "onde esse motivo se concentra geograficamente").
    """
    cursor = connection.cursor()
    sql = """
        SELECT
            mm.capitulo_cid,
            mm.municipio_codigo,
            m.nome AS municipio_nome,
            mm.total_internacoes
        FROM ADMIN.MOTIVO_POR_MUNICIPIO mm
        JOIN ADMIN.MUNICIPIOS_BRASILEIROS m
            ON SUBSTR(m.codigo_ibge, 1, 6) = mm.municipio_codigo
    """
    params = None
    if capitulo_cid is not None:
        sql += " WHERE mm.capitulo_cid = :capitulo_cid"
        params = {"capitulo_cid": capitulo_cid}
    sql += " ORDER BY mm.total_internacoes DESC"

    cursor.execute(sql, params)
    return _rows_to_df(cursor)
