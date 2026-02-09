"""
API request and response models.

These Pydantic models define the contract between frontend and backend.
"""

from enum import Enum

from pydantic import BaseModel, Field


class QueryStatus(str, Enum):
    """Status of the generated SQL query."""

    VALIDATED = "validated"
    DRAFT = "draft"
    REVIEW_REQUIRED = "review_required"
    ERROR = "error"


class Placeholder(BaseModel):
    """Represents a placeholder in the generated SQL."""

    token: str = Field(..., description="The placeholder token, e.g., '<CUSTOMERS_TABLE>'")
    meaning: str = Field(..., description="Human-readable explanation of what this placeholder represents")


class ColumnSchema(BaseModel):
    """Schema definition for a database column."""

    name: str = Field(..., description="Column name")
    type: str | None = Field(default=None, description="Column data type")
    description: str | None = Field(default=None, description="Human-readable description")
    primary_key: bool = Field(default=False, description="Whether this is a primary key")
    foreign_key: str | None = Field(
        default=None,
        description="Foreign key reference in format 'table.column'"
    )


class TableSchema(BaseModel):
    """Schema definition for a database table."""

    name: str = Field(..., description="Table name")
    description: str | None = Field(default=None, description="Human-readable description")
    columns: list[ColumnSchema] = Field(
        default_factory=list,
        description="List of columns in this table"
    )


class SchemaMetadata(BaseModel):
    """Complete database schema provided by the user."""

    tables: list[TableSchema] = Field(
        default_factory=list,
        description="List of tables in the schema"
    )


class QueryRequest(BaseModel):
    """Request payload for the /query endpoint."""

    question: str = Field(
        ...,
        description="Natural language question to convert to SQL",
        min_length=1,
        max_length=2000,
    )
    dialect: str = Field(
        default="postgres",
        description="SQL dialect to generate (postgres, mysql, sqlite)"
    )
    schema_metadata: SchemaMetadata | None = Field(
        default=None,
        description="Optional database schema for validation"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "Show me all customers from California",
                    "dialect": "postgres",
                    "schema_metadata": {
                        "tables": [
                            {
                                "name": "customers",
                                "columns": [
                                    {"name": "id", "type": "integer", "primary_key": True},
                                    {"name": "name", "type": "varchar"},
                                    {"name": "state", "type": "varchar"},
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    }


class QueryResponse(BaseModel):
    """Response payload from the /query endpoint."""

    sql: str | None = Field(
        ...,
        description="Generated SQL query (null if error)"
    )
    status: QueryStatus = Field(
        ...,
        description="Status of the generated query"
    )
    placeholders: list[Placeholder] = Field(
        default_factory=list,
        description="List of placeholders in the SQL that need to be replaced"
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about the generated SQL"
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Questions to help improve the query"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made during SQL generation"
    )
    policy_errors: list[str] = Field(
        default_factory=list,
        description="Policy violations that caused errors"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "sql": "SELECT * FROM customers WHERE state = 'California' LIMIT 50",
                    "status": "validated",
                    "placeholders": [],
                    "warnings": [],
                    "clarifying_questions": [],
                    "assumptions": ["Assuming 'California' matches exact string value"],
                    "policy_errors": [],
                }
            ]
        }
    }


class HealthResponse(BaseModel):
    """Response for health check endpoint."""

    status: str = "healthy"
    version: str = "0.1.0"


# Internal models for agent communication


class PlannerOutput(BaseModel):
    """Output from the PlannerAgent."""

    schema_sufficient: bool = Field(
        ...,
        description="Whether the provided schema is sufficient for the query"
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Questions to ask the user for clarification"
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Safe assumptions made about the query"
    )


class SqlWriterOutput(BaseModel):
    """Output from the SqlWriterAgent."""

    sql: str = Field(..., description="Generated SQL query")
    placeholders: list[Placeholder] = Field(
        default_factory=list,
        description="Placeholders used in the SQL"
    )


class PolicyGateOutput(BaseModel):
    """Output from the deterministic policy gate."""

    passed: bool = Field(..., description="Whether the SQL passed all policy checks")
    sql: str = Field(..., description="Potentially modified SQL (e.g., with LIMIT added)")
    status: QueryStatus = Field(..., description="Determined status for the query")
    warnings: list[str] = Field(default_factory=list, description="Warnings from policy checks")
    policy_errors: list[str] = Field(default_factory=list, description="Hard policy violations")



