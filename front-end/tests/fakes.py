"""Fake oracledb connection/cursor for testing the core service layer without a live DB."""

import oracledb


class FakeCursor:
    def __init__(self, description, rows):
        self.description = description
        self._rows = rows
        self.executed_sql = []
        self.executed_params = []

    def execute(self, sql, params=None):
        self.executed_sql.append(sql)
        self.executed_params.append(params)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConnection:
    """Returns a fresh cursor from a queue, one per call to .cursor().

    Each entry in `cursors` is a FakeCursor, consumed in order — lets a test
    stub out multiple sequential queries (e.g. a query followed by a JOIN lookup).
    """

    def __init__(self, cursors):
        self._cursors = list(cursors)

    def cursor(self):
        return self._cursors.pop(0)


def make_description(column_names):
    """Build a cursor.description-shaped tuple from plain column names."""
    return tuple((name, None, None, None, None, None, True) for name in column_names)


class FakePingConnection:
    """Fake oracledb connection whose .ping() can be told to raise, for
    testing stale-connection detection without a real Oracle error."""

    def __init__(self, ping_raises: bool):
        self._ping_raises = ping_raises

    def ping(self):
        if self._ping_raises:
            raise oracledb.Error("connection is dead")


class FakeVar:
    def __init__(self):
        self._value = None

    def set(self, value):
        self._value = value

    def getvalue(self):
        return self._value


class FakeAICursor:
    """Fake cursor for DBMS_CLOUD_AI.GENERATE calls: an anonymous PL/SQL
    block bound with a CLOB OUT var, keyed by the `action` bind."""

    def __init__(self, responses_by_action):
        self.responses_by_action = responses_by_action
        self.executed_calls = []
        self.var_types_requested = []

    def var(self, var_type):
        self.var_types_requested.append(var_type)
        return FakeVar()

    def execute(self, sql, result=None, prompt=None, profile_name=None, action=None):
        self.executed_calls.append(
            {"sql": sql, "prompt": prompt, "profile_name": profile_name, "action": action}
        )
        result.set(self.responses_by_action[action])

    def close(self):
        pass


class FakeAIConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor
