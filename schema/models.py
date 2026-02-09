"""
Internal schema representation models.

These dataclasses represent the canonical internal form of database schemas,
used throughout the application for validation and prompt generation.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    """Represents a database column."""

    name: str
    type: str | None = None
    description: str | None = None
    primary_key: bool = False
    foreign_key: str | None = None  # Format: "table.column"

    def to_prompt_string(self) -> str:
        """Format column for LLM prompt."""
        parts = [self.name]

        if self.type:
            parts.append(f"({self.type})")

        annotations = []
        if self.primary_key:
            annotations.append("PK")
        if self.foreign_key:
            annotations.append(f"FK->{self.foreign_key}")

        if annotations:
            parts.append(f"[{', '.join(annotations)}]")

        if self.description:
            parts.append(f"-- {self.description}")

        return " ".join(parts)


@dataclass(frozen=True)
class Table:
    """Represents a database table."""

    name: str
    columns: tuple[Column, ...] = field(default_factory=tuple)
    description: str | None = None

    def __post_init__(self) -> None:
        # Convert list to tuple if needed (for immutability)
        if isinstance(self.columns, list):
            object.__setattr__(self, "columns", tuple(self.columns))

    def has_column(self, column_name: str) -> bool:
        """Check if table has a column with the given name (case-insensitive)."""
        return any(c.name.lower() == column_name.lower() for c in self.columns)

    def get_column(self, column_name: str) -> Column | None:
        """Get column by name (case-insensitive)."""
        for col in self.columns:
            if col.name.lower() == column_name.lower():
                return col
        return None

    def get_column_names(self) -> list[str]:
        """Get list of all column names."""
        return [c.name for c in self.columns]

    def to_prompt_string(self) -> str:
        """Format table for LLM prompt."""
        lines = []

        header = f"TABLE: {self.name}"
        if self.description:
            header += f" -- {self.description}"
        lines.append(header)

        for col in self.columns:
            lines.append(f"  - {col.to_prompt_string()}")

        return "\n".join(lines)


@dataclass(frozen=True)
class SchemaContext:
    """
    Represents the complete database schema context.
    
    This is the canonical internal representation used throughout the application.
    """

    tables: tuple[Table, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Convert list to tuple if needed (for immutability)
        if isinstance(self.tables, list):
            object.__setattr__(self, "tables", tuple(self.tables))

    @property
    def is_empty(self) -> bool:
        """Check if schema has no tables."""
        return len(self.tables) == 0

    def has_table(self, table_name: str) -> bool:
        """Check if schema has a table with the given name (case-insensitive)."""
        return any(t.name.lower() == table_name.lower() for t in self.tables)

    def get_table(self, table_name: str) -> Table | None:
        """Get table by name (case-insensitive)."""
        for table in self.tables:
            if table.name.lower() == table_name.lower():
                return table
        return None

    def has_column(self, table_name: str, column_name: str) -> bool:
        """Check if a specific table has a specific column."""
        table = self.get_table(table_name)
        if table is None:
            return False
        return table.has_column(column_name)

    def get_table_names(self) -> list[str]:
        """Get list of all table names."""
        return [t.name for t in self.tables]

    def get_all_columns(self) -> list[tuple[str, str]]:
        """Get list of all (table_name, column_name) tuples."""
        result = []
        for table in self.tables:
            for col in table.columns:
                result.append((table.name, col.name))
        return result

    def to_prompt_string(self) -> str:
        """Format entire schema for LLM prompt."""
        if self.is_empty:
            return "No schema provided."

        lines = ["DATABASE SCHEMA:", ""]
        for table in self.tables:
            lines.append(table.to_prompt_string())
            lines.append("")

        return "\n".join(lines)

    def to_compact_string(self) -> str:
        """Format schema in compact form for shorter prompts."""
        if self.is_empty:
            return "No schema provided."

        parts = []
        for table in self.tables:
            cols = ", ".join(table.get_column_names())
            parts.append(f"{table.name}({cols})")

        return "Tables: " + "; ".join(parts)
