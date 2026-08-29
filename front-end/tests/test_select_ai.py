import oracledb

from core import select_ai
from tests.fakes import FakeAIConnection, FakeAICursor


def test_ask_select_ai_returns_answer_sql_and_rows():
    responses = {
        "showsql": "SELECT v.MUNICIPIO_NOME, v.INTERNACOES_POR_LEITO FROM ADMIN.VW_INDICADOR_COM_NOME v",
        "narrate": "Os municípios com mais internações por leito são Altinópolis e Embu-Guaçu.",
        "runsql": '[{"MUNICIPIO_NOME": "Altinópolis", "INTERNACOES_POR_LEITO": 31.24}]',
    }
    cursor = FakeAICursor(responses)
    connection = FakeAIConnection(cursor)

    result = select_ai.ask_select_ai(connection, "quais municipios tem mais internacoes por leito?")

    assert result["answer"] == responses["narrate"]
    assert result["sql"] == responses["showsql"]
    assert list(result["rows"]["MUNICIPIO_NOME"]) == ["Altinópolis"]
    assert result["rows"].iloc[0]["INTERNACOES_POR_LEITO"] == 31.24


def test_ask_select_ai_handles_empty_result_set():
    responses = {
        "showsql": "SELECT * FROM ADMIN.MOTIVOS_INTERNACAO WHERE 1=0",
        "narrate": "Não encontrei internações para esse critério.",
        "runsql": "[]",
    }
    cursor = FakeAICursor(responses)
    connection = FakeAIConnection(cursor)

    result = select_ai.ask_select_ai(connection, "pergunta sem resultados")

    assert result["rows"].empty


def test_ask_select_ai_passes_question_and_profile_to_every_call():
    responses = {"showsql": "SQL", "narrate": "resposta", "runsql": "[]"}
    cursor = FakeAICursor(responses)
    connection = FakeAIConnection(cursor)

    select_ai.ask_select_ai(connection, "minha pergunta", profile_name="GENAI_PROFILE")

    actions_called = {call["action"] for call in cursor.executed_calls}
    assert actions_called == {"showsql", "narrate", "runsql"}
    for call in cursor.executed_calls:
        assert call["prompt"] == "minha pergunta"
        assert call["profile_name"] == "GENAI_PROFILE"


def test_ask_select_ai_binds_clob_not_varchar():
    """DBMS_CLOUD_AI.GENERATE returns CLOB. Binding as plain str overflows
    Oracle's default buffer on long/verbose LLM responses (ORA-06502) —
    caught live, not by mocks, since FakeCursor doesn't enforce buffer
    sizes. This just guards against regressing back to the str bind.
    """
    responses = {"showsql": "SQL", "narrate": "resposta", "runsql": "[]"}
    cursor = FakeAICursor(responses)
    connection = FakeAIConnection(cursor)

    select_ai.ask_select_ai(connection, "minha pergunta")

    assert all(t == oracledb.DB_TYPE_CLOB for t in cursor.var_types_requested)


class _FakeLob:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


def test_ask_select_ai_unwraps_lob_values():
    responses = {
        "showsql": _FakeLob("SELECT 1 FROM DUAL"),
        "narrate": _FakeLob("resposta longa"),
        "runsql": _FakeLob("[]"),
    }
    cursor = FakeAICursor(responses)
    connection = FakeAIConnection(cursor)

    result = select_ai.ask_select_ai(connection, "minha pergunta")

    assert result["sql"] == "SELECT 1 FROM DUAL"
    assert result["answer"] == "resposta longa"
