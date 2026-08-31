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
    proporção de leitos SUS.

    O nome do município (antes obtido via JOIN com ADMIN.MUNICIPIOS_BRASILEIROS)
    agora vem denormalizado direto nesta tabela — o time de dados removeu a
    tabela de lookup e embutiu nome_municipio (e também população estimada /
    internações por mil habitantes, ainda não usadas nesta página) direto em
    ADMIN.INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO, a sucessora da antiga
    ADMIN.INDICADOR_CAPACIDADE_EXTENDIDO.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            municipio_codigo,
            nome_municipio AS municipio_nome,
            total_internacoes,
            permanencia_media_dias,
            estabelecimentos_distintos,
            leitos_existentes_total,
            leitos_sus_total,
            internacoes_por_leito,
            proporcao_leitos_sus,
            motivo_dominante,
            motivo_dominante_share
        FROM ADMIN.INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO
        ORDER BY internacoes_por_leito DESC
        """
    )
    return _rows_to_df(cursor)


def get_motivos_internacao(connection) -> pd.DataFrame:
    """Ranking geral dos capítulos CID-10 por volume, com permanência média.

    ADMIN.MOTIVOS_INTERNACAO teve seu column_list corrigido pelo time de
    dados — as colunas agora têm nomes e tipos corretos, então o workaround
    de column-shift que existia aqui (TO_NUMBER(municipio_codigo) pra
    recuperar o total real, ver histórico no git) não é mais necessário.
    """
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            capitulo_cid,
            total_internacoes,
            permanencia_media_dias
        FROM ADMIN.MOTIVOS_INTERNACAO
        ORDER BY total_internacoes DESC
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
    """Internações por capítulo CID-10 e município.

    O nome do município (antes obtido via JOIN com ADMIN.MUNICIPIOS_BRASILEIROS,
    removida do modelo) agora vem denormalizado direto em nome_municipio
    nesta própria tabela.

    Passe capitulo_cid pra filtrar por um único capítulo (ex.: pra uma visão
    de "onde esse motivo se concentra geograficamente").
    """
    cursor = connection.cursor()
    sql = """
        SELECT
            capitulo_cid,
            municipio_codigo,
            nome_municipio AS municipio_nome,
            total_internacoes
        FROM ADMIN.MOTIVO_POR_MUNICIPIO
    """
    params = None
    if capitulo_cid is not None:
        sql += " WHERE capitulo_cid = :capitulo_cid"
        params = {"capitulo_cid": capitulo_cid}
    sql += " ORDER BY total_internacoes DESC"

    cursor.execute(sql, params)
    return _rows_to_df(cursor)
