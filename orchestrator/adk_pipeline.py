"""
Google ADK Orchestrator for text-ql.

Uses Google ADK's LlmAgent, SequentialAgent, and Runner with Gemini 2.0 Flash
for natural language to SQL conversion.
"""

import asyncio
import logging
import os
import re
from typing import Any

# Set Google API key before importing ADK
from config.settings import get_settings
_settings = get_settings()
if _settings.google_api_key:
    os.environ["GOOGLE_API_KEY"] = _settings.google_api_key

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from api.models import (
    Placeholder,
    PlannerOutput,
    QueryResponse,
    QueryStatus,
    SqlWriterOutput,
)
from schema.models import SchemaContext
from schema.parser import parse_schema
from validation.policy_gate import run_policy_gate

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

GEMINI_MODEL = "gemini-2.0-flash"  # Free tier model
APP_NAME = "text_ql"
USER_ID = "default_user"

# ============================================================================
# Tool Functions (ADK will auto-wrap these as FunctionTools)
# ============================================================================

def parse_schema_tool(schema_json: str) -> dict:
    """
    Parse JSON schema into internal representation.
    
    Args:
        schema_json: JSON string of database schema with tables and columns.
        
    Returns:
        Dictionary with parsed schema info or error message.
    """
    import json
    
    if not schema_json or schema_json.strip() == "":
        return {"status": "empty", "tables": [], "message": "No schema provided"}
    
    try:
        data = json.loads(schema_json) if isinstance(schema_json, str) else schema_json
        schema = parse_schema(data)
        
        tables_info = []
        for table in schema.tables:
            cols = [{"name": c.name, "type": c.type} for c in table.columns]
            tables_info.append({"name": table.name, "columns": cols})
        
        return {
            "status": "parsed",
            "tables": tables_info,
            "message": f"Successfully parsed {len(tables_info)} table(s)"
        }
    except Exception as e:
        return {"status": "error", "tables": [], "message": str(e)}


def validate_sql_tool(sql: str, has_placeholders: bool = False) -> dict:
    """
    Validate SQL query against security policies.
    
    Args:
        sql: The SQL query to validate.
        has_placeholders: Whether the SQL contains placeholder tokens.
        
    Returns:
        Dictionary with validation results, warnings, and modified SQL.
    """
    settings = get_settings()
    
    # Basic validation
    if not sql or not sql.strip():
        return {
            "valid": False,
            "sql": sql,
            "status": "error",
            "warnings": [],
            "errors": ["Empty SQL query"]
        }
    
    warnings = []
    errors = []
    modified_sql = sql.strip()
    
    # Check statement type
    upper_sql = modified_sql.upper()
    is_select = upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")
    
    # Enforce LIMIT on SELECT
    if is_select and "LIMIT" not in upper_sql:
        modified_sql = modified_sql.rstrip(";") + f" LIMIT {settings.max_row_limit}"
        warnings.append(f"LIMIT {settings.max_row_limit} was enforced on the query")
    
    # Detect dangerous operations
    dangerous_ops = ["DROP", "TRUNCATE", "DELETE", "UPDATE", "INSERT"]
    for op in dangerous_ops:
        if upper_sql.startswith(op):
            warnings.append(f"⚠️ This is a {op} statement - review carefully before executing")
    
    # Detect placeholders
    placeholder_pattern = r"<[A-Z][A-Z0-9_]*>"
    if re.search(placeholder_pattern, modified_sql):
        has_placeholders = True
        warnings.append("SQL contains placeholders that need to be replaced")
    
    # Determine status
    if errors:
        status = "error"
    elif has_placeholders:
        status = "draft"
    elif not is_select:
        status = "review_required"
    else:
        status = "validated"
    
    return {
        "valid": len(errors) == 0,
        "sql": modified_sql,
        "status": status,
        "warnings": warnings,
        "errors": errors
    }


def extract_placeholders_tool(sql: str) -> list[dict]:
    """
    Extract placeholder tokens from SQL query.
    
    Args:
        sql: SQL query that may contain <PLACEHOLDER> tokens.
        
    Returns:
        List of placeholder dictionaries with token and meaning.
    """
    pattern = r"<[A-Z][A-Z0-9_]*>"
    matches = re.findall(pattern, sql)
    
    placeholders = []
    seen = set()
    
    for token in matches:
        if token in seen:
            continue
        seen.add(token)
        
        inner = token[1:-1].lower().replace("_", " ")
        if "table" in inner:
            meaning = f"Table name for {inner.replace('table', '').strip()}"
        elif "column" in inner:
            meaning = f"Column name for {inner.replace('column', '').strip()}"
        else:
            meaning = f"Value or identifier for {inner}"
        
        placeholders.append({"token": token, "meaning": meaning})
    
    return placeholders


# ============================================================================
# ADK Agent Definitions
# ============================================================================

def create_planner_agent() -> LlmAgent:
    """Create the Planner Agent using Gemini 2.0 Flash."""
    return LlmAgent(
        name="PlannerAgent",
        model=GEMINI_MODEL,
        description="Analyzes natural language questions and database schemas to plan SQL generation.",
        instruction="""You are a SQL Query Planner. Your job is to analyze the user's question and the provided database schema.

Your tasks:
1. Determine if the schema is sufficient to answer the question
2. Identify any clarifying questions needed
3. Document safe assumptions you're making

Respond in this exact JSON format:
{
    "schema_sufficient": true/false,
    "clarifying_questions": ["question1", "question2"],
    "assumptions": ["assumption1", "assumption2"]
}

If schema is missing or incomplete, set schema_sufficient to false and ask clarifying questions.
If you can reasonably answer with assumptions, document them and proceed.

Important: Only output the JSON, no other text.""",
        output_key="planner_output"
    )


def create_sql_writer_agent() -> LlmAgent:
    """Create the SQL Writer Agent using Gemini 2.0 Flash."""
    return LlmAgent(
        name="SqlWriterAgent",
        model=GEMINI_MODEL,
        description="Generates SQL queries from natural language questions.",
        instruction="""You are an expert SQL Writer. Generate a SQL query based on the user's question and schema.

Rules:
1. Use ONLY tables and columns from the provided schema
2. If schema is missing, use <PLACEHOLDER> tokens like <TABLE_NAME>, <COLUMN_NAME>
3. Write clean, efficient SQL
4. Support PostgreSQL, MySQL, and SQLite dialects
5. Do NOT include LIMIT - it will be added automatically

Output ONLY the SQL query, no explanations or markdown code blocks.

Example good output:
SELECT name, email FROM users WHERE state = 'California'

Example with placeholders (when schema is missing):
SELECT * FROM <USERS_TABLE> WHERE <NAME_COLUMN> LIKE 'S%'""",
        output_key="generated_sql"
    )


def create_validator_agent() -> LlmAgent:
    """Create the Validator Agent for final review."""
    return LlmAgent(
        name="ValidatorAgent",
        model=GEMINI_MODEL,
        description="Reviews and validates generated SQL queries.",
        instruction="""You are a SQL Validator. Review the generated SQL query for correctness.

Check for:
1. Syntax errors
2. Logical issues
3. Missing WHERE clauses on UPDATE/DELETE
4. Proper use of schema tables/columns

If the SQL looks correct, output it unchanged.
If there are issues, fix them and output the corrected SQL.

Output ONLY the final SQL query, no explanations.""",
        output_key="validated_sql",
        tools=[validate_sql_tool, extract_placeholders_tool]
    )


def create_text_ql_pipeline() -> SequentialAgent:
    """
    Create the complete text-ql pipeline using ADK SequentialAgent.
    
    Pipeline:
    1. PlannerAgent - Analyzes question and schema
    2. SqlWriterAgent - Generates SQL
    3. ValidatorAgent - Validates and finalizes SQL
    """
    planner = create_planner_agent()
    sql_writer = create_sql_writer_agent()
    validator = create_validator_agent()
    
    return SequentialAgent(
        name="TextQLPipeline",
        description="Converts natural language questions to validated SQL queries.",
        sub_agents=[planner, sql_writer, validator]
    )


# ============================================================================
# Pipeline Execution
# ============================================================================

# Global session service (reused across requests)
_session_service = None
_runner = None


def get_session_service() -> InMemorySessionService:
    """Get or create the session service singleton."""
    global _session_service
    if _session_service is None:
        _session_service = InMemorySessionService()
    return _session_service


def get_runner() -> Runner:
    """Get or create the runner singleton."""
    global _runner
    if _runner is None:
        pipeline = create_text_ql_pipeline()
        _runner = Runner(
            agent=pipeline,
            app_name=APP_NAME,
            session_service=get_session_service()
        )
    return _runner


async def run_pipeline_adk(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """
    Run the text-ql pipeline using Google ADK.
    
    Args:
        question: Natural language question
        dialect: SQL dialect (postgres, mysql, sqlite)
        schema_json: Optional database schema
        
    Returns:
        QueryResponse with generated SQL and metadata
    """
    import json
    import uuid
    
    runner = get_runner()
    session_service = get_session_service()
    
    # Create a unique session for this request
    session_id = str(uuid.uuid4())
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id
    )
    
    # Build the input message
    schema_str = json.dumps(schema_json, indent=2) if schema_json else "No schema provided"
    
    user_message = f"""
Question: {question}
SQL Dialect: {dialect}

Database Schema:
{schema_str}

Generate a SQL query to answer this question.
"""
    
    # Create the content
    content = types.Content(
        role="user",
        parts=[types.Part(text=user_message)]
    )
    
    # Run the pipeline
    final_response = None
    planner_output = None
    generated_sql = None
    
    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=content
        ):
            # Capture intermediate outputs from state
            if hasattr(event, 'actions') and event.actions:
                state_delta = getattr(event.actions, 'state_delta', {})
                if 'planner_output' in state_delta:
                    planner_output = state_delta['planner_output']
                if 'generated_sql' in state_delta:
                    generated_sql = state_delta['generated_sql']
                if 'validated_sql' in state_delta:
                    final_response = state_delta['validated_sql']
            
            # Get final response
            if hasattr(event, 'is_final_response') and event.is_final_response():
                if hasattr(event, 'content') and event.content:
                    for part in event.content.parts:
                        if hasattr(part, 'text'):
                            final_response = part.text
                            break
        
        # Parse planner output
        parsed_planner = _parse_planner_output(planner_output)
        
        # Get the SQL (prefer validated, fall back to generated)
        sql = final_response or generated_sql or ""
        sql = _clean_sql(sql)
        
        # Validate the SQL
        validation = validate_sql_tool(sql, has_placeholders=False)
        placeholders = extract_placeholders_tool(sql)
        
        # Build response
        return QueryResponse(
            sql=validation["sql"],
            status=QueryStatus(validation["status"]),
            placeholders=[Placeholder(**p) for p in placeholders],
            warnings=validation["warnings"],
            clarifying_questions=parsed_planner.get("clarifying_questions", []),
            assumptions=parsed_planner.get("assumptions", []),
            policy_errors=validation["errors"]
        )
        
    except Exception as e:
        logger.exception(f"ADK Pipeline error: {e}")
        return QueryResponse(
            sql=None,
            status=QueryStatus.ERROR,
            placeholders=[],
            warnings=[],
            clarifying_questions=[],
            assumptions=[],
            policy_errors=[f"Pipeline error: {str(e)}"]
        )
    finally:
        # Cleanup session
        try:
            await session_service.delete_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=session_id
            )
        except Exception:
            pass


def _parse_planner_output(output: str | None) -> dict:
    """Parse the planner's JSON output."""
    import json
    
    if not output:
        return {"schema_sufficient": False, "clarifying_questions": [], "assumptions": []}
    
    try:
        # Clean markdown if present
        cleaned = output.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(l for l in lines if not l.startswith("```"))
        
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"schema_sufficient": False, "clarifying_questions": [], "assumptions": []}


def _clean_sql(sql: str) -> str:
    """Clean up SQL response."""
    if not sql:
        return ""
    
    sql = sql.strip()
    
    # Remove markdown code blocks
    if sql.startswith("```"):
        lines = sql.split("\n")
        sql = "\n".join(l for l in lines if not l.startswith("```"))
    
    # Remove special tokens
    sql = re.sub(r'</?s>', '', sql)
    sql = re.sub(r'<\|.*?\|>', '', sql)
    
    return sql.strip()


# ============================================================================
# Synchronous Wrapper for FastAPI
# ============================================================================

def run_pipeline(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """Synchronous wrapper for the ADK pipeline."""
    try:
        # Check if we're already in an event loop
        loop = asyncio.get_running_loop()
        # If we're here, we're in an async context - this shouldn't happen
        # Fall back to the basic pipeline
        from orchestrator.root import run_pipeline as run_basic_pipeline
        return run_basic_pipeline(question, dialect, schema_json)
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
        return asyncio.run(run_pipeline_adk(question, dialect, schema_json))


async def run_pipeline_async(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """Async entry point for the ADK pipeline."""
    return await run_pipeline_adk(question, dialect, schema_json)
