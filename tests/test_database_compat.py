import unittest

from infra import database


class _Cursor:
    def __init__(self, users_table_exists=True):
        self.calls = []
        self.users_table_exists = users_table_exists

    def execute(self, statement, params=None):
        self.calls.append((statement, params))

    def fetchone(self):
        return ('users' if self.users_table_exists else None,)

    def close(self):
        pass


class _Connection:
    def __init__(self, users_table_exists=True):
        self.cursor_instance = _Cursor(users_table_exists)
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class DatabaseCompatibilityTests(unittest.TestCase):
    def test_compatibility_ddl_is_serialized_with_postgres_lock(self):
        connection = _Connection()

        database.install_compat(connection)

        lock_calls = [
            call for call in connection.cursor_instance.calls
            if call[0].startswith("SELECT pg_advisory_xact_lock")
        ]
        self.assertEqual(len(lock_calls), 1)
        self.assertTrue(all(
            call[1] == (database._COMPAT_ADVISORY_LOCK,)
            for call in lock_calls
        ))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_indexes_are_deferred_without_rolling_back_on_fresh_database(self):
        connection = _Connection(users_table_exists=False)

        database.install_compat(connection)

        statements = [call[0] for call in connection.cursor_instance.calls]
        self.assertFalse(any("CREATE UNIQUE INDEX" in sql for sql in statements))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
