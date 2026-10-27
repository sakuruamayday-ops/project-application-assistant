from contextlib import closing
import json
import sqlite3
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_client_error_reports import report, setup
from test_portal import load_app


def drop_projection(connection):
    connection.execute("DROP TRIGGER client_error_report_summaries_after_insert")
    connection.execute("DROP TRIGGER client_error_report_summaries_after_update")
    connection.execute("DROP TABLE client_error_report_summaries")
    connection.commit()


def add_user(connection, module, name="synthetic-owner", *, admin=True):
    return connection.execute(
        "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES (?,?,?,?)",
        (name, "synthetic-unused-hash", int(admin), module.isoformat(module.utc_now())),
    ).lastrowid


def add_feedback(connection, module, owner, subject="synthetic-feedback"):
    now = module.isoformat(module.utc_now())
    return connection.execute(
        """INSERT INTO feedback_messages(user_id,category,subject,content,status,created_at,updated_at)
        VALUES (?,'bug',?,'synthetic feedback body','pending',?,?)""",
        (owner, subject, now, now),
    ).lastrowid


def add_report(connection, feedback, owner, value):
    connection.execute(
        "INSERT INTO client_error_reports(feedback_id,user_id,request_id,diagnostic_json) VALUES (?,?,?,?)",
        (feedback, owner, str(uuid4()), value),
    )


def test_backfill_preserves_originals_and_existing_summaries_are_not_reparsed(tmp_path):
    module = load_app(tmp_path)
    values = [
        json.dumps({"code": "GC-LEGACY", "nested": {"conversation_context": "keep"},
                    "conversation_context": "large-context-marker" * 1000}, ensure_ascii=False),
        '{"summary":"no context","extra":[1,true,null]}',
        "malformed legacy JSON",
        "[1,2,3]",
        '"legacy scalar"',
    ]
    with closing(module.database()) as db:
        drop_projection(db)
        owner = add_user(db, module)
        for value in values:
            add_report(db, add_feedback(db, module, owner), owner, value)
        db.commit()
    module.init_database()
    with closing(module.database()) as db:
        assert [row[0] for row in db.execute(
            "SELECT diagnostic_json FROM client_error_reports ORDER BY feedback_id"
        )] == values
        rows = db.execute(
            """SELECT summary.diagnostic_json,
                      CASE WHEN json_valid(report.diagnostic_json)
                           THEN json_remove(report.diagnostic_json,'$.conversation_context') ELSE NULL END
               FROM client_error_reports report JOIN client_error_report_summaries summary
                 ON summary.feedback_id=report.feedback_id ORDER BY report.feedback_id"""
        ).fetchall()
        assert len(rows) == len(values)
        assert all(row[0] == row[1] for row in rows)
        assert json.loads(rows[0][0]) == {"code": "GC-LEGACY", "nested": {"conversation_context": "keep"}}
        assert rows[2][0] is None

        def reject_reparse(_value):
            raise AssertionError("Existing summaries must not parse the large JSON again")

        db.create_function("json_valid", 1, reject_reparse)
        before = db.total_changes
        module.initialize_client_error_report_summaries(db)
        assert db.total_changes == before


def test_failed_backfill_rolls_back_ddl_triggers_and_partial_projection(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as db:
        drop_projection(db)
        owner = add_user(db, module)
        for _ in range(2):
            add_report(db, add_feedback(db, module, owner), owner, '{"summary":"kept","conversation_context":"original"}')
        db.commit()
        calls = 0

        def fail_second_row(_value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("synthetic interruption during backfill")
            return 1

        db.create_function("json_valid", 1, fail_second_row)
        with pytest.raises(sqlite3.OperationalError):
            module.initialize_client_error_report_summaries(db)
        assert not db.in_transaction
        assert db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'client_error_report_summaries%'"
        ).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM client_error_reports").fetchone()[0] == 2
    module.init_database()
    with closing(module.database()) as db:
        assert db.execute("SELECT COUNT(*) FROM client_error_report_summaries").fetchone()[0] == 2


def test_old_connection_cannot_miss_projection_while_migration_holds_write_lock(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as writer:
        drop_projection(writer)
        owner = add_user(writer, module)
        existing = add_feedback(writer, module, owner)
        later = add_feedback(writer, module, owner)
        add_report(writer, existing, owner, '{"summary":"before","conversation_context":"original"}')
        writer.commit()
        writer.execute("PRAGMA busy_timeout=0")
        entered, release = threading.Event(), threading.Event()
        failures = []

        def migrate():
            try:
                with closing(module.database()) as migration:
                    def pause_validation(_value):
                        entered.set()
                        if not release.wait(5):
                            raise RuntimeError("migration test was not released")
                        return 1
                    migration.create_function("json_valid", 1, pause_validation)
                    module.initialize_client_error_report_summaries(migration)
            except BaseException as error:
                failures.append(error)

        thread = threading.Thread(target=migrate)
        thread.start()
        try:
            assert entered.wait(5), failures
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                add_report(writer, later, owner, '{"summary":"after"}')
            writer.rollback()
            assert writer.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='client_error_report_summaries'"
            ).fetchone()[0] == 0
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive()
        assert failures == []
        add_report(writer, later, owner, '{"summary":"after","conversation_context":"new"}')
        writer.commit()
        assert json.loads(writer.execute(
            "SELECT diagnostic_json FROM client_error_report_summaries WHERE feedback_id=?", (later,)
        ).fetchone()[0]) == {"summary": "after"}


def test_updates_rollbacks_and_deletes_keep_projection_in_the_same_transaction(tmp_path):
    module = load_app(tmp_path)
    with closing(module.database()) as db:
        owner = add_user(db, module)
        rid = add_feedback(db, module, owner)
        add_report(db, rid, owner, '{"summary":"initial","conversation_context":"original"}')
        db.commit()
        replacement = '{"expired":true,"report_id":1,"expired_at":"synthetic"}'
        db.execute("UPDATE client_error_reports SET diagnostic_json=? WHERE feedback_id=?", (replacement, rid))
        assert db.execute("SELECT diagnostic_json FROM client_error_report_summaries WHERE feedback_id=?", (rid,)).fetchone()[0] == replacement
        db.rollback()
        assert json.loads(db.execute("SELECT diagnostic_json FROM client_error_report_summaries WHERE feedback_id=?", (rid,)).fetchone()[0]) == {"summary": "initial"}
        db.execute("UPDATE client_error_reports SET diagnostic_json=? WHERE feedback_id=?", (replacement, rid))
        db.commit()
        assert db.execute("SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=?", (rid,)).fetchone()[0] == replacement
        db.execute("UPDATE client_error_reports SET diagnostic_json='bad legacy update' WHERE feedback_id=?", (rid,))
        assert db.execute("SELECT diagnostic_json FROM client_error_report_summaries WHERE feedback_id=?", (rid,)).fetchone()[0] is None
        db.execute("DELETE FROM client_error_reports WHERE feedback_id=?", (rid,))
        assert db.execute("SELECT COUNT(*) FROM client_error_report_summaries WHERE feedback_id=?", (rid,)).fetchone()[0] == 0
        db.commit()
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_list_uses_only_small_projection_and_preserves_redaction_isolation_and_full_export(tmp_path, monkeypatch):
    module, client, headers = setup(tmp_path)
    payload = report()
    payload["steps"] = "owner-only-diagnostic\n" + payload["steps"]
    payload["conversation_context"] = json.dumps({"marker": "original-context-kept", "password": "context-secret"})
    rid = client.post("/v1/client-error-reports", json=payload, headers=headers).json()["report_id"]
    client.post("/login", data={"username": "owner", "password": "synthetic-password-123"})
    with closing(module.database()) as db:
        full = db.execute("SELECT diagnostic_json FROM client_error_reports WHERE feedback_id=?", (rid,)).fetchone()[0]
        small = db.execute("SELECT diagnostic_json FROM client_error_report_summaries WHERE feedback_id=?", (rid,)).fetchone()[0]
        expected = json.loads(full)
        expected.pop("conversation_context")
        assert json.loads(small) == expected
        assert "syntheticsecret123" not in small and "syntheticpassword" not in small
        member = db.execute(
            "INSERT INTO users(username,real_name,password_hash,created_at) VALUES ('member','测试成员',?,?)",
            (module.password_hasher.hash("synthetic-member-password"), module.isoformat(module.utc_now())),
        ).lastrowid
        db.execute(
            "INSERT INTO registration_authorizations(real_name,identity_code,status,user_id,created_at,registered_at) VALUES ('测试成员','9001','registered',?,?,?)",
            (member, module.isoformat(module.utc_now()), module.isoformat(module.utc_now())),
        )
        own = add_feedback(db, module, member, "member-only-feedback")
        add_report(db, own, member, '{"client_version":"member-version","summary":"member-only-diagnostic"}')
        db.commit()
    original_database = module.database
    forbidden_reads = []

    def projection_only_database():
        db = original_database()
        def authorize(action, table, column, _database, _trigger):
            if action == sqlite3.SQLITE_READ and table == "client_error_reports" and column == "diagnostic_json":
                forbidden_reads.append((table, column))
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return db

    with monkeypatch.context() as patch:
        patch.setattr(module, "database", projection_only_database)
        for path in ["/portal", "/downloads", "/feedback?feedback_query=GC-REPORT"]:
            page = client.get(path)
            assert page.status_code == 200
            assert "original-context-kept" not in page.text
            assert "0.4.8-workbench.1" in page.text
        member_client = TestClient(module.app)
        login = member_client.post("/login", data={"username": "member", "password": "synthetic-member-password"})
        assert login.status_code == 200
        page = member_client.get("/feedback")
        assert page.status_code == 200 and "member-only-diagnostic" in page.text
        assert "owner-only-diagnostic" not in page.text
        assert forbidden_reads == []
    exported = client.get(f"/admin/feedback/{rid}/diagnostic")
    assert exported.status_code == 200 and exported.content == full.encode()
    assert "original-context-kept" in exported.text and "context-secret" not in exported.text
    assert member_client.get(f"/admin/feedback/{rid}/diagnostic", follow_redirects=False).status_code == 403


def test_invalid_legacy_projection_keeps_feedback_visible_and_original_export(tmp_path):
    module, client, _headers = setup(tmp_path)
    with closing(module.database()) as db:
        owner = db.execute("SELECT id FROM users WHERE username='owner'").fetchone()[0]
        rid = add_feedback(db, module, owner, "legacy-feedback-stays-visible")
        add_report(db, rid, owner, "invalid legacy JSON")
        array_id = add_feedback(db, module, owner, "legacy-array-stays-visible")
        add_report(db, array_id, owner, "[1,2,3]")
        db.commit()
    client.post("/login", data={"username": "owner", "password": "synthetic-password-123"})
    page = client.get("/feedback")
    assert page.status_code == 200
    assert "legacy-feedback-stays-visible" in page.text and "legacy-array-stays-visible" in page.text
    assert client.get(f"/admin/feedback/{rid}/diagnostic").content == b"invalid legacy JSON"
