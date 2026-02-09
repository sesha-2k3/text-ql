"""
Tests for the policy gate validation module.
"""

import pytest

from api.models import QueryStatus
from validation.policy_gate import (
    StatementType,
    check_multiple_statements,
    classify_statement,
    detect_placeholders,
    determine_status,
    enforce_limit,
    run_policy_gate,
)


class TestClassifyStatement:
    """Tests for statement classification."""

    def test_select_statement(self):
        assert classify_statement("SELECT * FROM users") == StatementType.SELECT
        assert classify_statement("select id from users") == StatementType.SELECT

    def test_with_cte(self):
        assert classify_statement("WITH cte AS (SELECT 1) SELECT * FROM cte") == StatementType.WITH

    def test_insert_statement(self):
        assert classify_statement("INSERT INTO users (name) VALUES ('test')") == StatementType.INSERT

    def test_update_statement(self):
        assert classify_statement("UPDATE users SET name = 'test'") == StatementType.UPDATE

    def test_delete_statement(self):
        assert classify_statement("DELETE FROM users WHERE id = 1") == StatementType.DELETE

    def test_drop_statement(self):
        assert classify_statement("DROP TABLE users") == StatementType.DROP

    def test_create_statement(self):
        assert classify_statement("CREATE TABLE users (id INT)") == StatementType.CREATE

    def test_truncate_statement(self):
        assert classify_statement("TRUNCATE TABLE users") == StatementType.TRUNCATE

    def test_alter_statement(self):
        assert classify_statement("ALTER TABLE users ADD COLUMN email VARCHAR") == StatementType.ALTER

    def test_grant_statement(self):
        assert classify_statement("GRANT SELECT ON users TO reader") == StatementType.GRANT

    def test_revoke_statement(self):
        assert classify_statement("REVOKE SELECT ON users FROM reader") == StatementType.REVOKE

    def test_unknown_statement(self):
        assert classify_statement("EXPLAIN SELECT * FROM users") == StatementType.UNKNOWN
        assert classify_statement("random text") == StatementType.UNKNOWN

    def test_whitespace_handling(self):
        assert classify_statement("   SELECT * FROM users") == StatementType.SELECT
        assert classify_statement("\n\nSELECT * FROM users") == StatementType.SELECT


class TestCheckMultipleStatements:
    """Tests for multiple statement detection."""

    def test_single_statement(self):
        assert check_multiple_statements("SELECT * FROM users") is False
        assert check_multiple_statements("SELECT * FROM users;") is False

    def test_multiple_statements(self):
        assert check_multiple_statements("SELECT 1; SELECT 2") is True
        assert check_multiple_statements("DELETE FROM users; SELECT * FROM users") is True

    def test_semicolon_in_string(self):
        # Semicolon inside string literal should not count
        assert check_multiple_statements("SELECT * FROM users WHERE name = 'test; value'") is False

    def test_trailing_semicolon(self):
        assert check_multiple_statements("SELECT * FROM users;") is False


class TestDetectPlaceholders:
    """Tests for placeholder detection."""

    def test_no_placeholders(self):
        result = detect_placeholders("SELECT * FROM users WHERE id = 1")
        assert result == []

    def test_table_placeholder(self):
        result = detect_placeholders("SELECT * FROM <USERS_TABLE>")
        assert len(result) == 1
        assert result[0]["token"] == "<USERS_TABLE>"

    def test_multiple_placeholders(self):
        result = detect_placeholders("SELECT * FROM <TABLE> WHERE <COLUMN> = 'test'")
        assert len(result) == 2
        tokens = {p["token"] for p in result}
        assert "<TABLE>" in tokens
        assert "<COLUMN>" in tokens

    def test_duplicate_placeholders(self):
        result = detect_placeholders("SELECT <COL>, <COL> FROM <TABLE>")
        assert len(result) == 2  # Should dedupe

    def test_placeholder_meaning(self):
        result = detect_placeholders("SELECT * FROM <CUSTOMERS_TABLE>")
        assert "table" in result[0]["meaning"].lower()


class TestEnforceLimit:
    """Tests for LIMIT enforcement."""

    def test_no_limit_adds_limit(self):
        sql, modified = enforce_limit("SELECT * FROM users", 50, StatementType.SELECT)
        assert "LIMIT 50" in sql
        assert modified is True

    def test_existing_limit_within_bounds(self):
        sql, modified = enforce_limit("SELECT * FROM users LIMIT 25", 50, StatementType.SELECT)
        assert "LIMIT 25" in sql
        assert modified is False

    def test_existing_limit_exceeds_bounds(self):
        sql, modified = enforce_limit("SELECT * FROM users LIMIT 100", 50, StatementType.SELECT)
        assert "LIMIT 50" in sql
        assert modified is True

    def test_trailing_semicolon_preserved(self):
        sql, modified = enforce_limit("SELECT * FROM users;", 50, StatementType.SELECT)
        assert sql.endswith(";")
        assert "LIMIT 50" in sql

    def test_non_select_not_modified(self):
        sql, modified = enforce_limit("INSERT INTO users (name) VALUES ('test')", 50, StatementType.INSERT)
        assert "LIMIT" not in sql
        assert modified is False

    def test_with_cte_gets_limit(self):
        sql, modified = enforce_limit("WITH cte AS (SELECT 1) SELECT * FROM cte", 50, StatementType.WITH)
        assert "LIMIT 50" in sql


class TestDetermineStatus:
    """Tests for status determination."""

    def test_validated_status(self):
        status = determine_status(
            statement_type=StatementType.SELECT,
            has_placeholders=False,
            has_schema_issues=False,
        )
        assert status == QueryStatus.VALIDATED

    def test_draft_with_placeholders(self):
        status = determine_status(
            statement_type=StatementType.SELECT,
            has_placeholders=True,
            has_schema_issues=False,
        )
        assert status == QueryStatus.DRAFT

    def test_draft_with_schema_issues(self):
        status = determine_status(
            statement_type=StatementType.SELECT,
            has_placeholders=False,
            has_schema_issues=True,
        )
        assert status == QueryStatus.DRAFT

    def test_review_required_for_insert(self):
        status = determine_status(
            statement_type=StatementType.INSERT,
            has_placeholders=False,
            has_schema_issues=False,
        )
        assert status == QueryStatus.REVIEW_REQUIRED

    def test_review_required_for_delete(self):
        status = determine_status(
            statement_type=StatementType.DELETE,
            has_placeholders=False,
            has_schema_issues=False,
        )
        assert status == QueryStatus.REVIEW_REQUIRED


class TestRunPolicyGate:
    """Integration tests for the full policy gate."""

    def test_simple_select_passes(self):
        result = run_policy_gate("SELECT * FROM users WHERE id = 1")
        assert result.passed is True
        assert result.status == QueryStatus.VALIDATED
        assert "LIMIT 50" in result.sql

    def test_select_with_placeholders_is_draft(self):
        result = run_policy_gate("SELECT * FROM <USERS_TABLE>")
        assert result.passed is True
        assert result.status == QueryStatus.DRAFT
        assert len(result.warnings) > 0

    def test_insert_is_review_required(self):
        result = run_policy_gate("INSERT INTO users (name) VALUES ('test')")
        assert result.passed is True
        assert result.status == QueryStatus.REVIEW_REQUIRED
        assert any("INSERT" in w for w in result.warnings)

    def test_delete_is_review_required(self):
        result = run_policy_gate("DELETE FROM users WHERE id = 1")
        assert result.passed is True
        assert result.status == QueryStatus.REVIEW_REQUIRED

    def test_multiple_statements_rejected(self):
        result = run_policy_gate("SELECT 1; DELETE FROM users")
        assert result.passed is False
        assert result.status == QueryStatus.ERROR
        assert len(result.policy_errors) > 0

    def test_unknown_statement_rejected(self):
        result = run_policy_gate("EXPLAIN SELECT * FROM users")
        assert result.passed is False
        assert result.status == QueryStatus.ERROR

    def test_drop_has_strong_warning(self):
        result = run_policy_gate("DROP TABLE users")
        assert result.passed is True
        assert result.status == QueryStatus.REVIEW_REQUIRED
        assert any("DROP" in w or "delete" in w.lower() for w in result.warnings)
