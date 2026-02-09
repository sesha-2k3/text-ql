"""
Schema consistency checker.

Extracts table and column references from SQL and validates them
against the provided schema.
"""

import re

from schema.models import SchemaContext


def extract_identifiers(sql: str) -> dict[str, list[str]]:
    """
    Extract table and column identifiers from SQL.
    
    This is a best-effort extraction using regex patterns.
    It handles common SQL patterns but may miss edge cases.
    
    Returns:
        Dict with 'tables' and 'columns' lists
    """
    # Remove string literals to avoid false matches
    cleaned = re.sub(r"'[^']*'", "''", sql)
    cleaned = re.sub(r'"[^"]*"', '""', cleaned)

    # Remove placeholders to avoid matching them
    cleaned = re.sub(r"<[A-Z][A-Z0-9_]*>", "PLACEHOLDER", cleaned)

    tables: set[str] = set()
    columns: set[str] = set()

    # Extract table names from FROM clause
    from_pattern = r"\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(from_pattern, cleaned, re.IGNORECASE):
        tables.add(match.group(1).lower())

    # Extract table names from JOIN clauses
    join_pattern = r"\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(join_pattern, cleaned, re.IGNORECASE):
        tables.add(match.group(1).lower())

    # Extract table names from INSERT INTO
    insert_pattern = r"\bINSERT\s+INTO\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(insert_pattern, cleaned, re.IGNORECASE):
        tables.add(match.group(1).lower())

    # Extract table names from UPDATE
    update_pattern = r"\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(update_pattern, cleaned, re.IGNORECASE):
        tables.add(match.group(1).lower())

    # Extract table names from DELETE FROM
    delete_pattern = r"\bDELETE\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(delete_pattern, cleaned, re.IGNORECASE):
        tables.add(match.group(1).lower())

    # Extract columns from SELECT clause (simple cases)
    # This catches "SELECT col1, col2" but not complex expressions
    select_pattern = r"\bSELECT\s+(.+?)\s+FROM\b"
    select_match = re.search(select_pattern, cleaned, re.IGNORECASE | re.DOTALL)
    if select_match:
        select_clause = select_match.group(1)
        # Split by comma and extract identifiers
        for part in select_clause.split(","):
            part = part.strip()
            # Handle "table.column" or just "column"
            col_match = re.match(r"([a-zA-Z_][a-zA-Z0-9_]*)(?:\.([a-zA-Z_][a-zA-Z0-9_]*))?", part)
            if col_match:
                if col_match.group(2):
                    # table.column format
                    columns.add(col_match.group(2).lower())
                elif part != "*" and part.upper() not in ("DISTINCT", "ALL"):
                    columns.add(col_match.group(1).lower())

    # Extract columns from WHERE clause
    where_pattern = r"\bWHERE\s+(.+?)(?:\bORDER\b|\bGROUP\b|\bLIMIT\b|\bHAVING\b|$)"
    where_match = re.search(where_pattern, cleaned, re.IGNORECASE | re.DOTALL)
    if where_match:
        where_clause = where_match.group(1)
        # Find identifiers before comparison operators
        col_patterns = [
            r"([a-zA-Z_][a-zA-Z0-9_]*)\s*[=<>!]",
            r"([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:IN|LIKE|BETWEEN|IS)",
        ]
        for pattern in col_patterns:
            for match in re.finditer(pattern, where_clause, re.IGNORECASE):
                col = match.group(1).lower()
                # Filter out SQL keywords
                if col.upper() not in ("AND", "OR", "NOT", "NULL", "TRUE", "FALSE"):
                    columns.add(col)

    # Extract columns from ORDER BY
    order_pattern = r"\bORDER\s+BY\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(order_pattern, cleaned, re.IGNORECASE):
        columns.add(match.group(1).lower())

    # Extract columns from GROUP BY
    group_pattern = r"\bGROUP\s+BY\s+([a-zA-Z_][a-zA-Z0-9_]*)"
    for match in re.finditer(group_pattern, cleaned, re.IGNORECASE):
        columns.add(match.group(1).lower())

    # Remove common SQL keywords that might have been captured
    sql_keywords = {
        "select", "from", "where", "and", "or", "not", "in", "like",
        "between", "is", "null", "true", "false", "as", "on", "join",
        "left", "right", "inner", "outer", "full", "cross", "order",
        "by", "group", "having", "limit", "offset", "distinct", "all",
        "asc", "desc", "case", "when", "then", "else", "end", "count",
        "sum", "avg", "min", "max", "placeholder"
    }

    tables = {t for t in tables if t not in sql_keywords}
    columns = {c for c in columns if c not in sql_keywords}

    return {
        "tables": list(tables),
        "columns": list(columns),
    }


def check_identifiers(
    identifiers: dict[str, list[str]],
    schema: SchemaContext
) -> list[str]:
    """
    Check if extracted identifiers exist in the schema.
    
    Returns:
        List of warning messages for missing identifiers
    """
    warnings: list[str] = []

    # Check tables
    schema_tables = {t.name.lower() for t in schema.tables}
    for table in identifiers["tables"]:
        if table not in schema_tables:
            warnings.append(f"Table '{table}' not found in provided schema")

    # Check columns (against all tables since we don't always know the source)
    all_columns = set()
    for table in schema.tables:
        for col in table.columns:
            all_columns.add(col.name.lower())

    for column in identifiers["columns"]:
        if column not in all_columns:
            warnings.append(f"Column '{column}' not found in provided schema")

    return warnings


def find_similar_identifiers(
    name: str,
    candidates: list[str],
    max_distance: int = 2
) -> list[str]:
    """
    Find identifiers similar to the given name using Levenshtein distance.
    
    This can be used to suggest corrections for typos.
    
    Args:
        name: The identifier to find matches for
        candidates: List of valid identifiers to compare against
        max_distance: Maximum edit distance to consider a match
        
    Returns:
        List of similar identifiers
    """
    similar = []

    for candidate in candidates:
        distance = levenshtein_distance(name.lower(), candidate.lower())
        if distance <= max_distance and distance > 0:
            similar.append(candidate)

    return similar


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate the Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # j+1 instead of j since previous_row and current_row are one character longer
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]
