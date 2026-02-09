"""
SqlWriterAgent: Generates SQL from natural language questions.

Supports:
- Groq API (llama-3.3-70b-versatile) for cloud inference
- Ollama (SQLCoder 7b) for local inference
"""

import json
import logging
import re
from pathlib import Path

import httpx
from groq import Groq

from api.models import Placeholder, PlannerOutput, SqlWriterOutput
from config.settings import get_settings
from schema.models import SchemaContext

logger = logging.getLogger(__name__)

# Load system prompt
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "sql_writer.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text() if PROMPT_PATH.exists() else ""


class SqlWriterAgent:
    """
    Agent responsible for generating SQL queries using Groq API.
    
    This agent:
    - Converts natural language to SQL
    - Uses placeholders when schema is missing
    - Handles all SQL statement types
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = get_settings()
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.sql_writer_model

        if not self.api_key:
            raise ValueError("Groq API key is required. Set GROQ_API_KEY environment variable.")

        self.client = Groq(api_key=self.api_key)

    def run(
        self,
        question: str,
        schema: SchemaContext | None,
        planner_output: PlannerOutput,
        dialect: str = "postgres",
    ) -> SqlWriterOutput:
        user_message = self._build_user_message(question, schema, planner_output, dialect)
        logger.debug(f"SqlWriterAgent input: {user_message[:500]}...")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            logger.debug(f"SqlWriterAgent raw response: {content}")
            return self._parse_response(content)

        except Exception as e:
            logger.error(f"SqlWriterAgent error: {e}")
            return SqlWriterOutput(
                sql="SELECT * FROM <TABLE> WHERE <CONDITION>",
                placeholders=[
                    Placeholder(token="<TABLE>", meaning="Target table"),
                    Placeholder(token="<CONDITION>", meaning="Filter condition"),
                ],
            )

    def _build_user_message(
        self,
        question: str,
        schema: SchemaContext | None,
        planner_output: PlannerOutput,
        dialect: str,
    ) -> str:
        parts = [
            f"Question: {question}",
            f"Dialect: {dialect}",
            "",
            "Schema:",
        ]

        if schema and not schema.is_empty:
            parts.append(schema.to_compact_string())
        else:
            parts.append("(No schema provided - use placeholders)")

        if planner_output.assumptions:
            parts.append("")
            parts.append("Assumptions to apply:")
            for assumption in planner_output.assumptions:
                parts.append(f"- {assumption}")

        return "\n".join(parts)

    def _parse_response(self, content: str | None) -> SqlWriterOutput:
        if not content:
            return SqlWriterOutput(sql="SELECT 1", placeholders=[])

        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    json_lines.append(line)
                cleaned = "\n".join(json_lines)

            data = json.loads(cleaned)

            placeholders = []
            for p in data.get("placeholders", []):
                if isinstance(p, dict) and "token" in p:
                    placeholders.append(
                        Placeholder(
                            token=p["token"],
                            meaning=p.get("meaning", "Unknown placeholder"),
                        )
                    )

            return SqlWriterOutput(
                sql=data.get("sql", "SELECT 1"),
                placeholders=placeholders,
            )

        except json.JSONDecodeError:
            cleaned = content.strip()
            if cleaned.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "CREATE", "DROP", "ALTER")):
                return SqlWriterOutput(sql=cleaned, placeholders=[])

            return SqlWriterOutput(
                sql="SELECT * FROM <TABLE>",
                placeholders=[Placeholder(token="<TABLE>", meaning="Target table")],
            )


class OllamaSqlWriterAgent:
    """
    SqlWriterAgent using Ollama for local SQLCoder inference.
    
    Requires Ollama running locally with SQLCoder model:
        ollama pull sqlcoder
        # or create from GGUF: ollama create sqlcoder -f Modelfile
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "sqlcoder",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.client = httpx.Client(timeout=120.0)  # SQL generation can take time

    def run(
        self,
        question: str,
        schema: SchemaContext | None,
        planner_output: PlannerOutput,
        dialect: str = "postgres",
    ) -> SqlWriterOutput:
        prompt = self._build_prompt(question, schema, planner_output, dialect)
        logger.debug(f"OllamaSqlWriterAgent prompt: {prompt[:500]}...")

        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
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
            
            # Prepend SELECT since our prompt ends with "SELECT" to guide the model
            if sql and not sql.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
                sql = "SELECT " + sql
            
            # Clean up the SQL - remove markdown code blocks if present
            sql = self._clean_sql(sql)
            
            logger.debug(f"OllamaSqlWriterAgent raw response: {sql}")

            # Detect placeholders
            placeholders = self._detect_placeholders(sql)

            return SqlWriterOutput(sql=sql, placeholders=placeholders)

        except httpx.ConnectError:
            logger.error("Failed to connect to Ollama. Is it running? (ollama serve)")
            return SqlWriterOutput(
                sql="SELECT * FROM <TABLE>",
                placeholders=[Placeholder(token="<TABLE>", meaning="Target table")],
            )
        except Exception as e:
            logger.error(f"OllamaSqlWriterAgent error: {e}")
            return SqlWriterOutput(
                sql="SELECT * FROM <TABLE>",
                placeholders=[Placeholder(token="<TABLE>", meaning="Target table")],
            )

    def _build_prompt(
        self,
        question: str,
        schema: SchemaContext | None,
        planner_output: PlannerOutput,
        dialect: str,
    ) -> str:
        """Build prompt in SQLCoder's expected format."""
        # Build detailed schema representation
        if schema and not schema.is_empty:
            schema_lines = []
            for table in schema.tables:
                cols = ", ".join([
                    f"{c.name} {c.type or 'TEXT'}" + (" PRIMARY KEY" if c.primary_key else "")
                    for c in table.columns
                ])
                schema_lines.append(f"CREATE TABLE {table.name} ({cols});")
            schema_str = "\n".join(schema_lines)
        else:
            schema_str = "-- No schema provided. Use <TABLE_NAME> and <COLUMN_NAME> placeholders for unknown identifiers."

        assumptions_str = ""
        if planner_output.assumptions:
            assumptions_str = "\n-- Assumptions: " + "; ".join(planner_output.assumptions)

        return f"""### Task
Generate a {dialect.upper()} SQL query to answer this question: {question}

### Database Schema
{schema_str}
{assumptions_str}

### Rules
1. Use ONLY the tables and columns from the schema above
2. If a table or column is missing from the schema, use placeholders like <TABLE_NAME> or <COLUMN_NAME>
3. Output ONLY the SQL query - no explanations, no comments, no variable assignments
4. Start your response with SELECT, INSERT, UPDATE, DELETE, or WITH

### SQL
SELECT"""

    def _clean_sql(self, sql: str) -> str:
        """Remove markdown code blocks, special tokens, and extra whitespace."""
        sql = sql.strip()
        
        # Remove special tokens from language models
        sql = re.sub(r'</?s>', '', sql)  # <s> and </s> tokens
        sql = re.sub(r'<\|.*?\|>', '', sql)  # <|endoftext|> etc.
        sql = re.sub(r'\[INST\].*?\[/INST\]', '', sql, flags=re.DOTALL)
        
        # Remove ```sql ... ``` blocks
        if sql.startswith("```"):
            lines = sql.split("\n")
            cleaned_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block or not line.startswith("```"):
                    cleaned_lines.append(line)
            sql = "\n".join(cleaned_lines).strip()
        
        # Remove any lines that are comments or variable assignments before SELECT
        lines = sql.strip().split('\n')
        clean_lines = []
        found_sql = False
        
        for line in lines:
            stripped = line.strip()
            # Skip empty lines and comments before SQL starts
            if not stripped or stripped.startswith('--') or stripped.startswith('#'):
                if found_sql:
                    clean_lines.append(line)
                continue
            # Skip variable assignments (e.g., "#_of_students = ...")
            if re.match(r'^#?\w+\s*=', stripped) and not found_sql:
                continue
            # Check if this line starts valid SQL
            if re.match(r'^(SELECT|INSERT|UPDATE|DELETE|WITH|CREATE|ALTER|DROP)\b', stripped, re.IGNORECASE):
                found_sql = True
            if found_sql:
                clean_lines.append(line)
        
        sql = '\n'.join(clean_lines).strip()
        
        # If we still don't have valid SQL, try to extract SELECT statement
        if not re.match(r'^(SELECT|INSERT|UPDATE|DELETE|WITH)\b', sql, re.IGNORECASE):
            match = re.search(r'(SELECT\s+.+?)(?:;|$)', sql, re.IGNORECASE | re.DOTALL)
            if match:
                sql = match.group(1).strip()
        
        return sql

    def _detect_placeholders(self, sql: str) -> list[Placeholder]:
        """Detect <PLACEHOLDER> tokens in the SQL."""
        settings = get_settings()
        matches = re.findall(settings.placeholder_pattern, sql)
        
        placeholders = []
        seen = set()
        for match in matches:
            if match in seen:
                continue
            seen.add(match)
            
            # Generate human-readable meaning
            inner = match[1:-1]  # Remove < and >
            words = inner.lower().replace("_", " ")
            
            if "table" in words:
                meaning = f"Table name for {words.replace('table', '').strip()}"
            elif "column" in words:
                meaning = f"Column name for {words.replace('column', '').strip()}"
            else:
                meaning = f"Value or identifier for {words}"
            
            placeholders.append(Placeholder(token=match, meaning=meaning))
        
        return placeholders


# Keep for backwards compatibility
LocalSqlWriterAgent = OllamaSqlWriterAgent


def create_sql_writer_agent(
    api_key: str | None = None,
    model: str | None = None,
    use_local: bool = False,
    local_model_path: str | None = None,  # Deprecated, kept for compatibility
) -> SqlWriterAgent | OllamaSqlWriterAgent:
    """
    Factory function to create a SqlWriterAgent.
    
    Args:
        api_key: Groq API key (for cloud inference)
        model: Model name
        use_local: Whether to use local Ollama SQLCoder
        local_model_path: Deprecated - Ollama manages models internally
        
    Returns:
        SqlWriterAgent (Groq) or OllamaSqlWriterAgent (Ollama) instance
    """
    settings = get_settings()

    if use_local or settings.use_local_sqlcoder:
        return OllamaSqlWriterAgent(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
        )

    return SqlWriterAgent(api_key=api_key, model=model)