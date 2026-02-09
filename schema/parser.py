"""
Schema parser for converting user input to internal SchemaContext.

Supports structured JSON format as the single input format.
"""

from typing import Any

from schema.models import Column, SchemaContext, Table


class SchemaParseError(Exception):
    """Raised when schema parsing fails."""

    pass


def parse_column(data: dict[str, Any]) -> Column:
    """
    Parse a column definition from JSON.
    
    Expected format:
    {
        "name": "column_name",          # required
        "type": "varchar",              # optional
        "description": "...",           # optional
        "primary_key": true,            # optional
        "foreign_key": "table.column"   # optional
    }
    """
    if not isinstance(data, dict):
        raise SchemaParseError(f"Column must be an object, got {type(data).__name__}")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise SchemaParseError("Column must have a 'name' field of type string")

    return Column(
        name=name.strip(),
        type=data.get("type"),
        description=data.get("description"),
        primary_key=bool(data.get("primary_key", False)),
        foreign_key=data.get("foreign_key"),
    )


def parse_table(data: dict[str, Any]) -> Table:
    """
    Parse a table definition from JSON.
    
    Expected format:
    {
        "name": "table_name",           # required
        "description": "...",           # optional
        "columns": [...]                # required, array of column objects
    }
    """
    if not isinstance(data, dict):
        raise SchemaParseError(f"Table must be an object, got {type(data).__name__}")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise SchemaParseError("Table must have a 'name' field of type string")

    columns_data = data.get("columns", [])
    if not isinstance(columns_data, list):
        raise SchemaParseError(f"Table 'columns' must be an array, got {type(columns_data).__name__}")

    columns = []
    for i, col_data in enumerate(columns_data):
        try:
            columns.append(parse_column(col_data))
        except SchemaParseError as e:
            raise SchemaParseError(f"Error parsing column {i} in table '{name}': {e}") from e

    return Table(
        name=name.strip(),
        columns=tuple(columns),
        description=data.get("description"),
    )


def parse_schema(data: dict[str, Any] | None) -> SchemaContext:
    """
    Parse a complete schema definition from JSON.
    
    Expected format:
    {
        "tables": [
            {
                "name": "table_name",
                "columns": [
                    {"name": "col1", "type": "int"},
                    {"name": "col2", "type": "varchar"}
                ]
            }
        ]
    }
    
    Returns empty SchemaContext if data is None or empty.
    """
    if data is None:
        return SchemaContext(tables=tuple())

    if not isinstance(data, dict):
        raise SchemaParseError(f"Schema must be an object, got {type(data).__name__}")

    tables_data = data.get("tables", [])
    if not isinstance(tables_data, list):
        raise SchemaParseError(f"Schema 'tables' must be an array, got {type(tables_data).__name__}")

    if not tables_data:
        return SchemaContext(tables=tuple())

    tables = []
    for i, table_data in enumerate(tables_data):
        try:
            tables.append(parse_table(table_data))
        except SchemaParseError as e:
            raise SchemaParseError(f"Error parsing table {i}: {e}") from e

    return SchemaContext(tables=tuple(tables))


def validate_schema(schema: SchemaContext) -> list[str]:
    """
    Validate a parsed schema and return any warnings.
    
    This doesn't raise errors, just returns potential issues.
    """
    warnings = []

    # Check for duplicate table names
    table_names = [t.name.lower() for t in schema.tables]
    seen = set()
    for name in table_names:
        if name in seen:
            warnings.append(f"Duplicate table name: '{name}'")
        seen.add(name)

    # Check for tables with no columns
    for table in schema.tables:
        if not table.columns:
            warnings.append(f"Table '{table.name}' has no columns defined")

        # Check for duplicate column names within table
        col_names = [c.name.lower() for c in table.columns]
        col_seen = set()
        for col_name in col_names:
            if col_name in col_seen:
                warnings.append(f"Duplicate column name '{col_name}' in table '{table.name}'")
            col_seen.add(col_name)

    # Validate foreign key references
    for table in schema.tables:
        for col in table.columns:
            if col.foreign_key:
                parts = col.foreign_key.split(".")
                if len(parts) != 2:
                    warnings.append(
                        f"Invalid foreign key format '{col.foreign_key}' "
                        f"in {table.name}.{col.name}. Expected 'table.column'"
                    )
                else:
                    ref_table, ref_col = parts
                    if not schema.has_table(ref_table):
                        warnings.append(
                            f"Foreign key references non-existent table '{ref_table}' "
                            f"in {table.name}.{col.name}"
                        )
                    elif not schema.has_column(ref_table, ref_col):
                        warnings.append(
                            f"Foreign key references non-existent column '{ref_col}' "
                            f"in table '{ref_table}' (from {table.name}.{col.name})"
                        )

    return warnings
