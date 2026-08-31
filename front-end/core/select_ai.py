"""Oracle Select AI (DBMS_CLOUD_AI) wrapper — natural-language question in,
narrated answer + generated SQL + result rows out. No Streamlit calls here.
"""

from __future__ import annotations

import json

import oracledb
import pandas as pd

DEFAULT_PROFILE = "GENAI_PROFILE"

_GENERATE_BLOCK = """
BEGIN
    :result := DBMS_CLOUD_AI.GENERATE(
        prompt       => :prompt,
        profile_name => :profile_name,
        action       => :action
    );
END;
"""


def _generate(connection, prompt: str, profile_name: str, action: str) -> str:
    # DBMS_CLOUD_AI.GENERATE returns CLOB, not VARCHAR2 — binding the OUT
    # var as a plain str overflows Oracle's default buffer size on long
    # responses (ORA-06502: character string buffer too small), which only
    # showed up live against a verbose LLM response, not in mocked tests.
    cursor = connection.cursor()
    result_var = cursor.var(oracledb.DB_TYPE_CLOB)
    cursor.execute(_GENERATE_BLOCK, result=result_var, prompt=prompt, profile_name=profile_name, action=action)
    value = result_var.getvalue()
    return value.read() if hasattr(value, "read") else value


def ask_select_ai(connection, pergunta: str, profile_name: str = DEFAULT_PROFILE) -> dict:
    """Ask a natural-language question against the Select AI profile.

    Returns {"answer": str, "sql": str, "rows": pd.DataFrame}. Deliberately
    does not use action="chat" — it isn't grounded in the database schema
    and will fabricate plausible-looking data instead of using real rows
    (confirmed by testing directly against the live profile).
    """
    sql = _generate(connection, pergunta, profile_name, "showsql")
    answer = _generate(connection, pergunta, profile_name, "narrate")
    rows_json = _generate(connection, pergunta, profile_name, "runsql")
    rows = pd.DataFrame(json.loads(rows_json)) if rows_json and rows_json.strip() != "[]" else pd.DataFrame()
    return {"answer": answer, "sql": sql, "rows": rows}
