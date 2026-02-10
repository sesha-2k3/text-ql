"""
Hybrid Google ADK Orchestrator for text-ql.

Uses:
- Gemini 2.0 Flash (via LlmAgent) for Planning and Validation
- SQLCoder-7B (via Ollama + Custom BaseAgent) for SQL Generation

This demonstrates ADK's flexibility to mix LLM providers within a single pipeline.
"""

import asyncio
import logging
import os
import re
import json
from typing import Any, AsyncGenerator, ClassVar

import httpx

# Set Google API key before importing ADK
from config.settings import get_settings
_settings = get_settings()
if _settings.google_api_key:
    os.environ["GOOGLE_API_KEY"] = _settings.google_api_key

from google.adk.agents import LlmAgent, SequentialAgent, BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import Field

from api.models import (
    Placeholder,
    QueryResponse,
    QueryStatus,
)
from schema.models import SchemaContext
from schema.parser import parse_schema

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

GEMINI_MODEL = "gemini-2.0-flash"  # Free tier model
APP_NAME = "text_ql_hybrid"
USER_ID = "default_user"


# ============================================================================
# Custom SQLCoder Agent (extends BaseAgent with Pydantic fields)
# ============================================================================

class OllamaSqlCoderAgent(BaseAgent):
    """
    Custom ADK Agent that uses SQLCoder-7B via Ollama for SQL generation.
    
    This demonstrates how to integrate non-Gemini models into an ADK pipeline
    by extending BaseAgent and implementing the _run_async_impl method.
    
    Note: BaseAgent is a Pydantic model, so we must declare fields properly.
    """
    
    # Declare Pydantic fields (these are allowed by BaseAgent)
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="sqlcoder")
    output_key: str = Field(default="generated_sql")
    
    # Use ClassVar for the HTTP client (not a Pydantic field)
    _client: ClassVar[httpx.AsyncClient | None] = None
    
    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        """Get or create the shared HTTP client."""
        if cls._client is None:
            cls._client = httpx.AsyncClient(timeout=120.0)
        return cls._client
    
    async def _run_async_impl(
        self, 
        ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        """
        Execute the SQLCoder agent.
        
        This method is called by ADK's Runner when this agent's turn comes
        in the SequentialAgent pipeline.
        """
        logger.info(f"[{self.name}] Starting SQL generation with SQLCoder-7B")
        
        # Get the user's original message and planner output from state
        user_message = self._get_user_message(ctx)
        planner_output = ctx.session.state.get("planner_output", "{}")
        
        # Parse planner output for assumptions
        try:
            planner_data = json.loads(planner_output) if isinstance(planner_output, str) else planner_output
            assumptions = planner_data.get("assumptions", [])
        except (json.JSONDecodeError, AttributeError):
            assumptions = []
        
        # Build the prompt for SQLCoder
        prompt = self._build_sqlcoder_prompt(user_message, assumptions)
        
        logger.debug(f"[{self.name}] Prompt: {prompt[:500]}...")
        
        # Get Ollama URL (strip trailing slash)
        base_url = self.ollama_base_url.rstrip("/")
        
        try:
            # Call Ollama API
            client = self.get_client()
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 500,
                    },
                },
            )
            response.raise_for_status()
            
            result = response.json()
            sql = result.get("response", "").strip()
            
            # Clean up the SQL
            sql = self._clean_sql(sql)
            
            logger.info(f"[{self.name}] Generated SQL: {sql[:100]}...")
            
        except httpx.ConnectError:
            logger.error(f"[{self.name}] Failed to connect to Ollama at {base_url}")
            sql = "SELECT * FROM <TABLE> -- Error: Could not connect to Ollama"
        except Exception as e:
            logger.error(f"[{self.name}] Error: {e}")
            sql = f"SELECT * FROM <TABLE> -- Error: {str(e)}"
        
        # Create the response event with state update
        # This saves the SQL to state[output_key] for the next agent
        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part(text=sql)]
            ),
            actions=EventActions(
                state_delta={self.output_key: sql}
            )
        )
    
    def _get_user_message(self, ctx: InvocationContext) -> str:
        """Extract the original user message from session events."""
        for event in reversed(ctx.session.events):
            if event.content and event.content.role == "user":
                for part in event.content.parts:
                    if hasattr(part, 'text'):
                        return part.text
        return ""
    
    def _build_sqlcoder_prompt(self, user_message: str, assumptions: list[str]) -> str:
        """Build prompt in SQLCoder's expected format."""
        # Extract schema from user message if present
        schema_match = re.search(r'Database Schema:\s*(\{.*?\}|\[.*?\]|CREATE TABLE.*?(?=\n\n|$))', 
                                  user_message, re.DOTALL | re.IGNORECASE)
        
        if schema_match:
            schema_str = schema_match.group(1).strip()
            # Try to convert JSON schema to CREATE TABLE format
            try:
                schema_data = json.loads(schema_str)
                if isinstance(schema_data, dict) and "tables" in schema_data:
                    schema_lines = []
                    for table in schema_data["tables"]:
                        cols = ", ".join([
                            f"{c['name']} {c.get('type', 'TEXT')}"
                            for c in table.get("columns", [])
                        ])
                        schema_lines.append(f"CREATE TABLE {table['name']} ({cols});")
                    schema_str = "\n".join(schema_lines)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        else:
            schema_str = "-- No schema provided. Use <TABLE_NAME> and <COLUMN_NAME> placeholders."
        
        # Extract the question
        question_match = re.search(r'Question:\s*(.+?)(?=\n|SQL Dialect|Database Schema|$)', 
                                    user_message, re.DOTALL)
        question = question_match.group(1).strip() if question_match else user_message
        
        # Extract dialect
        dialect_match = re.search(r'SQL Dialect:\s*(\w+)', user_message)
        dialect = dialect_match.group(1).upper() if dialect_match else "POSTGRES"
        
        assumptions_str = ""
        if assumptions:
            assumptions_str = "\n-- Assumptions: " + "; ".join(assumptions)
        
        return f"""### Task
Generate a {dialect} SQL query to answer this question: {question}

### Database Schema
{schema_str}
{assumptions_str}

### Rules
1. Use ONLY the tables and columns from the schema above
2. If a table or column is missing, use placeholders like <TABLE_NAME> or <COLUMN_NAME>
3. Output ONLY the SQL query - no explanations, no comments, no markdown
4. Start with SELECT, INSERT, UPDATE, DELETE, or WITH

### SQL
SELECT"""
    
    def _clean_sql(self, sql: str) -> str:
        """Clean up SQL response from SQLCoder."""
        if not sql:
            return "SELECT * FROM <TABLE>"
        
        # Prepend SELECT if needed (prompt ends with SELECT)
        if not sql.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
            sql = "SELECT " + sql
        
        # Remove special tokens - be VERY specific to avoid removing SQL operators
        # Use word boundaries and whitespace to be safe
        sql = re.sub(r'^\s*<s>\s*', '', sql)           # <s> at start
        sql = re.sub(r'\s*</s>\s*$', '', sql)          # </s> at end
        sql = re.sub(r'\s+<s>\s+', ' ', sql)           # <s> in middle (with spaces)
        sql = re.sub(r'\s+</s>\s+', ' ', sql)          # </s> in middle (with spaces)
        sql = re.sub(r'<\|[^>]*\|>', '', sql)          # <|endoftext|> etc.
        sql = re.sub(r'\[INST\].*?\[/INST\]', '', sql, flags=re.DOTALL)
        
        # Remove markdown code blocks
        sql = re.sub(r'^```\w*\n?', '', sql)
        sql = re.sub(r'\n?```$', '', sql)
        
        # Remove variable assignments before SQL
        lines = sql.strip().split('\n')
        clean_lines = []
        found_sql = False
        
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('--') or stripped.startswith('#'):
                if found_sql:
                    clean_lines.append(line)
                continue
            if re.match(r'^#?\w+\s*=', stripped) and not found_sql:
                continue
            if re.match(r'^(SELECT|INSERT|UPDATE|DELETE|WITH)\b', stripped, re.IGNORECASE):
                found_sql = True
            if found_sql:
                clean_lines.append(line)
        
        sql = '\n'.join(clean_lines).strip()
        
        # Final validation
        if not re.match(r'^(SELECT|INSERT|UPDATE|DELETE|WITH)\b', sql, re.IGNORECASE):
            match = re.search(r'(SELECT\s+.+?)(?:;|$)', sql, re.IGNORECASE | re.DOTALL)
            if match:
                sql = match.group(1).strip()
        
        return sql or "SELECT * FROM <TABLE>"


# ============================================================================
# Tool Functions for Gemini Agents
# ============================================================================

def validate_sql(sql: str) -> dict:
    """
    Validate SQL query and enforce policies.
    
    Args:
        sql: The SQL query to validate.
        
    Returns:
        Dictionary with validation results.
    """
    settings = get_settings()
    
    if not sql or not sql.strip():
        return {"valid": False, "sql": sql, "status": "error", "warnings": [], "errors": ["Empty SQL"]}
    
    warnings = []
    modified_sql = sql.strip()
    upper_sql = modified_sql.upper()
    
    # Enforce LIMIT
    is_select = upper_sql.startswith("SELECT") or upper_sql.startswith("WITH")
    if is_select and "LIMIT" not in upper_sql:
        modified_sql = modified_sql.rstrip(";") + f" LIMIT {settings.max_row_limit}"
        warnings.append(f"LIMIT {settings.max_row_limit} was enforced")
    
    # Detect placeholders
    if re.search(r"<[A-Z][A-Z0-9_]*>", modified_sql):
        warnings.append("SQL contains placeholders that need to be replaced")
        status = "draft"
    elif not is_select:
        status = "review_required"
    else:
        status = "validated"
    
    return {"valid": True, "sql": modified_sql, "status": status, "warnings": warnings, "errors": []}


def extract_placeholders(sql: str) -> list[dict]:
    """Extract placeholder tokens from SQL."""
    matches = re.findall(r"<[A-Z][A-Z0-9_]*>", sql)
    placeholders = []
    seen = set()
    
    for token in matches:
        if token in seen:
            continue
        seen.add(token)
        inner = token[1:-1].lower().replace("_", " ")
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
        description="Analyzes natural language questions and database schemas.",
        instruction="""You are a SQL Query Planner. Analyze the user's question and schema.

Output this exact JSON format:
{
    "schema_sufficient": true/false,
    "clarifying_questions": ["question1", "question2"],
    "assumptions": ["assumption1", "assumption2"]
}

Rules:
- If schema is missing/incomplete, set schema_sufficient to false
- If you can make safe assumptions, document them and set schema_sufficient to true
- Output ONLY the JSON, no other text""",
        output_key="planner_output"
    )


def create_validator_agent() -> LlmAgent:
    """Create the Validator Agent using Gemini 2.0 Flash."""
    return LlmAgent(
        name="ValidatorAgent",
        model=GEMINI_MODEL,
        description="Reviews and validates generated SQL queries.",
        instruction="""You are a SQL Validator. Review the SQL in state['generated_sql'].

Your tasks:
1. Check for syntax errors
2. Verify it matches the user's question
3. Fix any issues

Output ONLY the final SQL query, no explanations.
If the SQL is correct, output it unchanged.
If there are issues, fix them first.""",
        output_key="validated_sql",
        tools=[validate_sql, extract_placeholders]
    )


def create_sqlcoder_agent() -> OllamaSqlCoderAgent:
    """Create the SQLCoder Agent using Ollama."""
    settings = get_settings()
    return OllamaSqlCoderAgent(
        name="SqlCoderAgent",
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        output_key="generated_sql",
        description="Generates SQL queries using SQLCoder-7B via Ollama."
    )


def create_hybrid_pipeline() -> SequentialAgent:
    """
    Create the hybrid text-ql pipeline.
    
    Pipeline:
    1. PlannerAgent (Gemini 2.0 Flash) - Analyzes question and schema
    2. SqlCoderAgent (SQLCoder-7B via Ollama) - Generates SQL
    3. ValidatorAgent (Gemini 2.0 Flash) - Validates and finalizes
    """
    return SequentialAgent(
        name="TextQLHybridPipeline",
        description="Hybrid pipeline: Gemini for planning/validation, SQLCoder for SQL generation.",
        sub_agents=[
            create_planner_agent(),
            create_sqlcoder_agent(),
            create_validator_agent()
        ]
    )


# ============================================================================
# Pipeline Execution
# ============================================================================

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
        pipeline = create_hybrid_pipeline()
        _runner = Runner(
            agent=pipeline,
            app_name=APP_NAME,
            session_service=get_session_service()
        )
    return _runner


async def run_hybrid_pipeline(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """
    Run the hybrid text-ql pipeline.
    
    Falls back to Groq if Gemini rate limit is exceeded.
    
    Args:
        question: Natural language question
        dialect: SQL dialect (postgres, mysql, sqlite)
        schema_json: Optional database schema
        
    Returns:
        QueryResponse with generated SQL and metadata
    """
    import uuid
    
    runner = get_runner()
    session_service = get_session_service()
    
    session_id = str(uuid.uuid4())
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=session_id
    )
    
    # Build input message
    schema_str = json.dumps(schema_json, indent=2) if schema_json else "No schema provided"
    
    user_message = f"""Question: {question}
SQL Dialect: {dialect}

Database Schema:
{schema_str}

Generate a SQL query to answer this question."""
    
    content = types.Content(
        role="user",
        parts=[types.Part(text=user_message)]
    )
    
    # Track outputs
    final_sql = None
    planner_output = None
    
    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=session_id,
            new_message=content
        ):
            # Capture state updates
            if hasattr(event, 'actions') and event.actions:
                state_delta = getattr(event.actions, 'state_delta', {}) or {}
                if 'planner_output' in state_delta:
                    planner_output = state_delta['planner_output']
                if 'generated_sql' in state_delta:
                    final_sql = state_delta['generated_sql']
                if 'validated_sql' in state_delta:
                    final_sql = state_delta['validated_sql']
            
            # Get final response text
            if hasattr(event, 'is_final_response') and event.is_final_response():
                if hasattr(event, 'content') and event.content:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            # Only override if it looks like SQL
                            text = part.text.strip()
                            if text.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
                                final_sql = text
        
        # Parse planner output
        parsed_planner = _parse_planner_output(planner_output)
        
        # Validate final SQL
        validation = validate_sql(final_sql or "")
        placeholders = extract_placeholders(validation["sql"])
        
        return QueryResponse(
            sql=validation["sql"],
            status=QueryStatus(validation["status"]),
            placeholders=[Placeholder(**p) for p in placeholders],
            warnings=validation["warnings"],
            clarifying_questions=parsed_planner.get("clarifying_questions", []),
            assumptions=parsed_planner.get("assumptions", []),
            policy_errors=validation.get("errors", [])
        )
        
    except Exception as e:
        error_str = str(e).lower()
        
        # Check if it's a rate limit error (429) or quota exhausted
        is_rate_limit = (
            "429" in error_str or 
            "resource_exhausted" in error_str or 
            "quota" in error_str or
            "rate" in error_str
        )
        
        if is_rate_limit:
            logger.warning(f"Gemini rate limited, falling back to Groq: {e}")
            try:
                # Fall back to Groq-based pipeline
                return await _run_groq_fallback(question, dialect, schema_json)
            except Exception as fallback_error:
                logger.exception(f"Groq fallback also failed: {fallback_error}")
                return QueryResponse(
                    sql=None,
                    status=QueryStatus.ERROR,
                    placeholders=[],
                    warnings=["Gemini rate limited, Groq fallback also failed"],
                    clarifying_questions=[],
                    assumptions=[],
                    policy_errors=[f"Both Gemini and Groq failed: {str(fallback_error)}"]
                )
        
        logger.exception(f"Hybrid Pipeline error: {e}")
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
        try:
            await session_service.delete_session(
                app_name=APP_NAME,
                user_id=USER_ID,
                session_id=session_id
            )
        except Exception:
            pass


async def _run_groq_fallback(
    question: str,
    dialect: str,
    schema_json: dict[str, Any] | None,
) -> QueryResponse:
    """
    Fallback to Groq when Gemini is rate limited.
    
    Uses the basic pipeline from root.py which uses Groq + Ollama.
    """
    logger.info("Using Groq fallback pipeline...")
    
    # Import and run the basic pipeline (which uses Groq)
    from orchestrator.root import run_pipeline as run_basic_pipeline
    
    # Run in a thread pool since the basic pipeline is synchronous
    import asyncio
    loop = asyncio.get_event_loop()
    
    response = await loop.run_in_executor(
        None,
        lambda: run_basic_pipeline(question, dialect, schema_json)
    )
    
    # Add a warning that we used the fallback
    warnings = list(response.warnings)
    warnings.insert(0, "⚡ Used Groq fallback (Gemini rate limited)")
    
    return QueryResponse(
        sql=response.sql,
        status=response.status,
        placeholders=response.placeholders,
        warnings=warnings,
        clarifying_questions=response.clarifying_questions,
        assumptions=response.assumptions,
        policy_errors=response.policy_errors
    )


def _parse_planner_output(output: str | None) -> dict:
    """Parse the planner's JSON output."""
    if not output:
        return {"schema_sufficient": False, "clarifying_questions": [], "assumptions": []}
    
    try:
        cleaned = output.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(l for l in lines if not l.startswith("```"))
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return {"schema_sufficient": False, "clarifying_questions": [], "assumptions": []}


# ============================================================================
# Entry Points
# ============================================================================

def run_pipeline(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """Synchronous wrapper for the hybrid pipeline."""
    try:
        loop = asyncio.get_running_loop()
        # Already in async context - use fallback
        from orchestrator.root import run_pipeline as run_basic
        return run_basic(question, dialect, schema_json)
    except RuntimeError:
        return asyncio.run(run_hybrid_pipeline(question, dialect, schema_json))


async def run_pipeline_async(
    question: str,
    dialect: str = "postgres",
    schema_json: dict[str, Any] | None = None,
) -> QueryResponse:
    """Async entry point for the hybrid pipeline."""
    return await run_hybrid_pipeline(question, dialect, schema_json)


# Export the pipeline creator for external use
create_text_ql_pipeline = create_hybrid_pipeline
