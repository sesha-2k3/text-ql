"""
Deterministic policy gate for SQL validation.

This module contains all hard validation rules that don't require LLM inference.
It checks for forbidden patterns, enforces LIMIT, detects placeholders, etc.
"""

import re
from enum import Enum

from api.models import PolicyGateOutput, QueryStatus
from config.settings import get_settings
from schema.models import SchemaContext


class StatementType(str, Enum):
    """Classification of SQL statement types."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DROP = "DROP"
    TRUNCATE = "TRUNCATE"
    ALTER = "ALTER"
    CREATE = "CREATE"
    GRANT = "GRANT"
    REVOKE = "REVOKE"
    WITH = "WITH"  # CTE, treated same as SELECT
    UNKNOWN = "UNKNOWN"


def classify_statement(sql: str) -> StatementType:
    """
    Classify the SQL statement type based on its first keyword.
    
    Args:
        sql: The SQL string to classify
        
    Returns:
        StatementType enum value
    """
    normalized = sql.strip().upper()

    # Check each statement type
    if normalized.startswith("SELECT"):
        return StatementType.SELECT
    elif normalized.startswith("WITH"):
        return StatementType.WITH
    elif normalized.startswith("INSERT"):
        return StatementType.INSERT
    elif normalized.startswith("UPDATE"):
        return StatementType.UPDATE
    elif normalized.startswith("DELETE"):
        return StatementType.DELETE
    elif normalized.startswith("DROP"):
        return StatementType.DROP
    elif normalized.startswith("TRUNCATE"):
        return StatementType.TRUNCATE
    elif normalized.startswith("ALTER"):
        return StatementType.ALTER
    elif normalized.startswith("CREATE"):
        return StatementType.CREATE
    elif normalized.startswith("GRANT"):
        return StatementType.GRANT
    elif normalized.startswith("REVOKE"):
        return StatementType.REVOKE
    else:
        return StatementType.UNKNOWN


def is_read_only_statement(statement_type: StatementType) -> bool:
    """Check if the statement type is read-only (SELECT or WITH)."""
    return statement_type in (StatementType.SELECT, StatementType.WITH)


def check_multiple_statements(sql: str) -> bool:
    """
    Check if the SQL contains multiple statements.
    
    This is a simple check for semicolons followed by non-whitespace.
    We reject multiple statements to avoid ambiguity.
    
    Returns:
        True if multiple statements detected, False otherwise
    """
    # Remove string literals to avoid false positives
    # Simple approach: replace quoted strings with placeholders
    cleaned = re.sub(r"'[^']*'", "''", sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)

    # Split by semicolon and check for multiple non-empty statements
    parts = [p.strip() for p in cleaned.split(";") if p.strip()]

    return len(parts) > 1


def detect_placeholders(sql: str) -> list[dict[str, str]]:
    """
    Detect placeholder tokens in the SQL.
    
    Placeholders are in the format <UPPER_SNAKE_CASE>.
    
    Returns:
        List of dicts with 'token' and 'meaning' keys
    """
    settings = get_settings()
    pattern = settings.placeholder_pattern
    matches = re.findall(pattern, sql)

    # Generate meanings based on common patterns
    placeholders = []
    seen = set()

    for token in matches:
        if token in seen:
            continue
        seen.add(token)

        # Generate a human-readable meaning
        inner = token[1:-1]  # Remove < and >
        words = inner.lower().replace("_", " ")

        if "table" in words:
            meaning = f"Table name for {words.replace('table', '').strip()}"
        elif "column" in words:
            meaning = f"Column name for {words.replace('column', '').strip()}"
        else:
            meaning = f"Value or identifier for {words}"

        placeholders.append({"token": token, "meaning": meaning})

    return placeholders


def enforce_limit(sql: str, max_limit: int, statement_type: StatementType) -> tuple[str, bool]:
    """
    Ensure SELECT/WITH statements have a LIMIT clause.
    
    Args:
        sql: The SQL string
        max_limit: Maximum allowed LIMIT value
        statement_type: The classified statement type
        
    Returns:
        Tuple of (modified_sql, was_modified)
    """
    # Only enforce LIMIT on SELECT/WITH statements
    if not is_read_only_statement(statement_type):
        return sql, False

    # Check if LIMIT already exists (case-insensitive)
    limit_pattern = r"\bLIMIT\s+(\d+)\b"
    match = re.search(limit_pattern, sql, re.IGNORECASE)

    if match:
        # LIMIT exists, check if it's within bounds
        current_limit = int(match.group(1))
        if current_limit > max_limit:
            # Replace with max_limit
            modified = re.sub(
                limit_pattern,
                f"LIMIT {max_limit}",
                sql,
                flags=re.IGNORECASE
            )
            return modified, True
        return sql, False

    # No LIMIT found, add one
    # Handle trailing semicolon
    sql_stripped = sql.rstrip()
    if sql_stripped.endswith(";"):
        modified = sql_stripped[:-1] + f" LIMIT {max_limit};"
    else:
        modified = sql_stripped + f" LIMIT {max_limit}"

    return modified, True


def get_statement_warning(statement_type: StatementType) -> str | None:
    """Get warning message for a given statement type."""
    settings = get_settings()
    return settings.modifying_keywords.get(statement_type.value)


def run_policy_gate(
    sql: str,
    schema: SchemaContext | None = None,
    has_placeholders_from_writer: bool = False,
) -> PolicyGateOutput:
    """
    Run all deterministic policy checks on the SQL.
    
    This is the main entry point for the policy gate.
    
    Args:
        sql: The generated SQL to validate
        schema: Optional schema context for consistency checks
        has_placeholders_from_writer: Whether the writer reported placeholders
        
    Returns:
        PolicyGateOutput with results of all checks
    """
    settings = get_settings()
    warnings: list[str] = []
    policy_errors: list[str] = []
    modified_sql = sql

    # 1. Classify statement type
    statement_type = classify_statement(sql)

    if statement_type == StatementType.UNKNOWN:
        policy_errors.append(
            "Unable to determine SQL statement type. Query must start with a valid SQL keyword."
        )
        return PolicyGateOutput(
            passed=False,
            sql=sql,
            status=QueryStatus.ERROR,
            warnings=warnings,
            policy_errors=policy_errors,
        )

    # 2. Check for multiple statements (always rejected)
    if check_multiple_statements(sql):
        policy_errors.append(
            "Multiple SQL statements detected. Please submit one query at a time."
        )
        return PolicyGateOutput(
            passed=False,
            sql=sql,
            status=QueryStatus.ERROR,
            warnings=warnings,
            policy_errors=policy_errors,
        )

    # 3. Add warning for non-SELECT statements
    statement_warning = get_statement_warning(statement_type)
    if statement_warning:
        warnings.append(f"⚠️ {statement_warning}")

    # 4. Enforce LIMIT for SELECT statements
    if is_read_only_statement(statement_type):
        modified_sql, limit_modified = enforce_limit(sql, settings.max_row_limit, statement_type)
        if limit_modified:
            warnings.append(f"LIMIT {settings.max_row_limit} was enforced on the query")

    # 5. Detect placeholders
    placeholders = detect_placeholders(modified_sql)
    has_placeholders = len(placeholders) > 0 or has_placeholders_from_writer

    if has_placeholders and not any("placeholder" in w.lower() for w in warnings):
        warnings.append("SQL contains placeholders that need to be replaced with actual values")

    # 6. Schema consistency check (if schema provided and SELECT)
    schema_issues = []
    if schema and not schema.is_empty and is_read_only_statement(statement_type):
        schema_issues = check_schema_consistency(modified_sql, schema)
        warnings.extend(schema_issues)

    # 7. Determine final status
    status = determine_status(
        statement_type=statement_type,
        has_placeholders=has_placeholders,
        has_schema_issues=len(schema_issues) > 0,
    )

    return PolicyGateOutput(
        passed=True,  # We passed if we got here without policy_errors
        sql=modified_sql,
        status=status,
        warnings=warnings,
        policy_errors=policy_errors,
    )


def determine_status(
    statement_type: StatementType,
    has_placeholders: bool,
    has_schema_issues: bool,
) -> QueryStatus:
    """
    Determine the appropriate status based on various factors.
    
    Logic:
    - Non-SELECT statements → review_required
    - Has placeholders → draft
    - Has schema issues → draft
    - Otherwise → validated
    """
    # Non-read-only statements always need review
    if not is_read_only_statement(statement_type):
        return QueryStatus.REVIEW_REQUIRED

    # Placeholders mean draft status
    if has_placeholders:
        return QueryStatus.DRAFT

    # Schema issues mean draft status
    if has_schema_issues:
        return QueryStatus.DRAFT

    # All good!
    return QueryStatus.VALIDATED


def check_schema_consistency(sql: str, schema: SchemaContext) -> list[str]:
    """
    Check if the SQL references tables/columns that exist in the schema.
    
    This is a best-effort check using regex patterns.
    It may have false positives/negatives but provides useful warnings.
    
    Returns:
        List of warning messages for potential issues
    """
    from validation.schema_checker import extract_identifiers, check_identifiers

    identifiers = extract_identifiers(sql)
    return check_identifiers(identifiers, schema)
