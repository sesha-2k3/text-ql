"""
Orchestrator for the text-ql pipeline.

Pipeline: Planner (Groq/LLaMA 3.3) → SqlWriter (Ollama/SQLCoder 7b) → PolicyGate → Response

Fully synchronous implementation - no async complexity.
"""

import logging
from typing import Any

from api.models import (
    Placeholder,
    PlannerOutput,
    QueryResponse,
    QueryStatus,
    SqlWriterOutput,
)
from agents.planner import create_planner_agent
from agents.sql_writer import create_sql_writer_agent
from config.settings import get_settings
from schema.models import SchemaContext
from schema.parser import parse_schema
from validation.policy_gate import run_policy_gate

logger = logging.getLogger(__name__)


# ============================================================================
# Pipeline Functions
# ============================================================================

def parse_schema_fn(schema_json: dict | None) -> tuple[SchemaContext | None, str | None]:
    """Parse JSON schema into internal representation."""
    if schema_json is None:
        return SchemaContext(tables=tuple()), None
    
    try:
        schema = parse_schema(schema_json)
        return schema, None
    except Exception as e:
        logger.error(f"Schema parsing error: {e}")
        return SchemaContext(tables=tuple()), str(e)


def run_planner_fn(question: str, schema: SchemaContext | None, dialect: str) -> PlannerOutput:
    """Run the PlannerAgent (Groq/LLaMA 3.3)."""
    planner = create_planner_agent()
    try:
        return planner.run(question=question, schema=schema, dialect=dialect)
    except Exception as e:
        logger.error(f"Planner error: {e}")
        return PlannerOutput(
            schema_sufficient=False,
            clarifying_questions=[],
            assumptions=[],
        )


def run_sql_writer_fn(
    question: str,
    schema: SchemaContext | None,
    planner_output: PlannerOutput,
    dialect: str
) -> SqlWriterOutput:
    """Run the SqlWriterAgent (Ollama/SQLCoder)."""
    settings = get_settings()
    writer = create_sql_writer_agent(use_local=settings.use_local_sqlcoder)
    try:
        return writer.run(
            question=question,
            schema=schema,
            planner_output=planner_output,
            dialect=dialect,
        )
    except Exception as e:
        logger.error(f"SQL Writer error: {e}")
        return SqlWriterOutput(
            sql="SELECT * FROM <TABLE>",
            placeholders=[Placeholder(token="<TABLE>", meaning="Target table")],
        )


def run_policy_gate_fn(sql: str, schema: SchemaContext | None, has_placeholders: bool):
    """Run deterministic policy validation."""
    return run_policy_gate(
        sql=sql,
        schema=schema,
        has_placeholders_from_writer=has_placeholders,
    )


def build_response_fn(
    planner_output: PlannerOutput,
    writer_output: SqlWriterOutput,
    gate_output: Any,
    schema_error: str | None = None,
) -> QueryResponse:
    """Build the final QueryResponse."""
    if schema_error:
        return QueryResponse(
            sql=None,
            status=QueryStatus.ERROR,
            placeholders=[],
            warnings=[],
            clarifying_questions=[],
            assumptions=[],
            policy_errors=[f"Invalid schema format: {schema_error}"],
        )

    all_warnings = list(gate_output.warnings)
    all_questions = list(planner_output.clarifying_questions)

    if gate_output.status == QueryStatus.DRAFT:
        if writer_output.placeholders and not any("schema" in q.lower() for q in all_questions):
            all_questions.append("Please provide your database schema to remove placeholders.")

    return QueryResponse(
        sql=gate_output.sql,
        status=gate_output.status,
        placeholders=writer_output.placeholders,
        warnings=all_warnings,
        clarifying_questions=all_questions,
        assumptions=planner_output.assumptions,
        policy_errors=gate_output.policy_errors,
    )


# ============================================================================
# Main Pipeline Runner (Synchronous)
# ============================================================================

def run_pipeline(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """
    Run the text-ql pipeline.

    Stages:
    1. Schema parsing (deterministic)
    2. Planner (Groq/LLaMA 3.3)
    3. SQL Writer (Ollama/SQLCoder)
    4. Policy Gate (deterministic)
    5. Response Builder
    """
    # Stage 1: Parse schema
    logger.info("Stage 1: Parsing schema")
    schema, schema_error = parse_schema_fn(schema_json)
    
    if schema_error:
        return build_response_fn(
            planner_output=PlannerOutput(schema_sufficient=False, clarifying_questions=[], assumptions=[]),
            writer_output=SqlWriterOutput(sql="", placeholders=[]),
            gate_output=type('GateOutput', (), {
                'warnings': [], 'status': QueryStatus.ERROR, 'sql': None, 'policy_errors': []
            })(),
            schema_error=schema_error,
        )

    # Stage 2: Run planner
    logger.info("Stage 2: Running Planner (Groq/LLaMA 3.3)")
    planner_output = run_planner_fn(question, schema, dialect)
    logger.debug(f"Planner: schema_sufficient={planner_output.schema_sufficient}")

    # Stage 3: Run SQL writer
    logger.info("Stage 3: Running SQL Writer (Ollama/SQLCoder)")
    writer_output = run_sql_writer_fn(question, schema, planner_output, dialect)
    logger.debug(f"Writer: sql={writer_output.sql[:100] if writer_output.sql else 'None'}...")

    # Stage 4: Policy gate
    logger.info("Stage 4: Running Policy Gate")
    has_placeholders = len(writer_output.placeholders) > 0
    gate_output = run_policy_gate_fn(writer_output.sql, schema, has_placeholders)
    logger.debug(f"Gate: status={gate_output.status}")

    # Stage 5: Build response
    logger.info("Stage 5: Building response")
    response = build_response_fn(planner_output, writer_output, gate_output)

    return response


# Alias for compatibility
async def run_pipeline_async(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """Async wrapper that just calls the sync pipeline."""
    return run_pipeline(question, dialect, schema_json)
