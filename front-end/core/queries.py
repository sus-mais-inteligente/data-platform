"""Oracle data-access functions. Each function takes a live connection and
returns a pandas DataFrame — no Streamlit calls anywhere in this module, so
it can be exercised with a fake connection/cursor in tests.
"""

from __future__ import annotations

import pandas as pd


def _rows_to_df(cursor) -> pd.DataFrame:
    columns = [col[0].lower() for col in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def get_indicador_capacidade_extendido(connection) -> pd.DataFrame:
    """Município-level capacity indicator, extended with motivo dominante and
    proporção de leitos SUS, joined with município names.
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
    """Overall ranking of capítulos CID-10 by volume.

    WORKAROUND: the ADMIN.MOTIVOS_INTERNACAO External Table has a shifted
    column_list — the column named MUNICIPIO_CODIGO actually holds the real
    total_internacoes count, and the column named TOTAL_INTERNACOES actually
    holds a small decimal (likely permanencia_media_dias), not a município
    code or a totals column. Confirmed by cross-checking sums against
    MOTIVO_POR_MES, which is correctly labeled. Aliased here to their real
    meaning rather than fixed at the source, per product decision — flagged
    to the team as a data-platform bug to fix in the External Table DDL.

    MUNICIPIO_CODIGO is declared VARCHAR2 (it's meant to hold codes-as-text),
    so the real count it's holding here comes back as a string without an
    explicit cast — TO_NUMBER avoids that count sorting lexicographically
    instead of numerically wherever it's charted.
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
    """Internações by capítulo CID-10 and mês (for the seasonality heatmap)."""
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
    """Overall monthly internação volume, derived by summing MOTIVO_POR_MES
    across capítulos — there is no dedicated Oracle table for this.
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
    """Internações by capítulo CID-10 and município, joined with município names.

    Pass capitulo_cid to filter to a single capítulo (e.g. for a "where does
    this motivo concentrate geographically" view).
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
