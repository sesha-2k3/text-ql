# text-ql

Natural Language to SQL converter using a multi-agent architecture.

## Overview

text-ql converts natural language questions into SQL queries. It uses a pipeline of specialized agents:

1. **PlannerAgent** - Analyzes questions, identifies missing schema info, generates clarifying questions
2. **SqlWriterAgent** - Generates SQL from natural language using the analyzed context
3. **PolicyGate** - Deterministic validation layer that enforces safety rules

## Features

- **Natural language input** - Ask questions in plain English
- **Schema-aware generation** - Provide your database schema for accurate queries
- **Placeholder system** - When schema is missing, generates SQL with `<PLACEHOLDER>` tokens
- **Smart validation** - Enforces LIMIT, detects dangerous operations, validates against schema
- **All SQL types** - Supports SELECT, INSERT, UPDATE, DELETE with appropriate warnings
- **Multiple dialects** - PostgreSQL, MySQL, SQLite

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Groq API key

### Backend Setup

```bash
# Navigate to project
cd text-ql

# Create models directory and download SQLCoder 7b
mkdir -p models
# Download from HuggingFace (example using wget)
wget -O models/sqlcoder-7b-q4_0.gguf \
  "https://huggingface.co/TheBloke/sqlcoder-7B-GGUF/resolve/main/sqlcoder-7b.Q4_0.gguf"

# Create .env file
cp .env.example .env
# Edit .env and add your GROQ_API_KEY

# Install dependencies with uv
uv pip install -r requirements.txt

# Or with pip
pip install -r requirements.txt

# Run the server
python -m uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The UI will be available at `http://localhost:3000`

## API Usage

### Endpoint: POST /api/query

**Request:**
```json
{
  "question": "Show me all customers from California",
  "dialect": "postgres",
  "schema_metadata": {
    "tables": [
      {
        "name": "customers",
        "columns": [
          {"name": "id", "type": "integer", "primary_key": true},
          {"name": "name", "type": "varchar"},
          {"name": "state", "type": "varchar"}
        ]
      }
    ]
  }
}
```

**Response:**
```json
{
  "sql": "SELECT id, name, state FROM customers WHERE state = 'California' LIMIT 50",
  "status": "validated",
  "placeholders": [],
  "warnings": [],
  "clarifying_questions": [],
  "assumptions": ["Assuming 'California' matches exact value in state column"],
  "policy_errors": []
}
```

### Status Values

| Status | Meaning |
|--------|---------|
| `validated` | Query is complete and validated against schema |
| `draft` | Query has placeholders or schema issues |
| `review_required` | Modifying statement (INSERT/UPDATE/DELETE) - review before running |
| `error` | Policy violation (e.g., multiple statements) |

## Project Structure

```
text-ql/
├── app/                    # FastAPI application
│   └── main.py            # App entrypoint
├── api/                    # API layer
│   ├── models.py          # Pydantic request/response models
│   └── routes.py          # Route handlers
├── orchestrator/           # Pipeline orchestration
│   └── root.py            # Main orchestrator
├── agents/                 # LLM agents
│   ├── planner.py         # PlannerAgent
│   └── sql_writer.py      # SqlWriterAgent
├── validation/             # Deterministic validation
│   ├── policy_gate.py     # Policy enforcement
│   └── schema_checker.py  # Schema validation
├── schema/                 # Schema handling
│   ├── models.py          # Internal schema models
│   └── parser.py          # JSON schema parser
├── config/                 # Configuration
│   └── settings.py        # Pydantic settings
├── prompts/                # LLM prompts
│   ├── planner.txt
│   └── sql_writer.txt
├── tests/                  # Test suite
├── frontend/               # Next.js frontend
│   ├── app/               # App router pages
│   ├── components/        # React components
│   └── lib/               # Utilities and types
└── pyproject.toml         # Python dependencies
```

## Configuration

Environment variables (`.env`):

```bash
# Required
GROQ_API_KEY=your_key_here

# Optional
PLANNER_MODEL=llama-3.3-70b-versatile
SQL_WRITER_MODEL=llama-3.3-70b-versatile
DEFAULT_DIALECT=postgres
MAX_ROW_LIMIT=50
DEBUG=false
```

## Running Tests

```bash
# Install dev dependencies first
uv pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_policy_gate.py -v
```

## Development

```bash
# Format code
ruff format .

# Lint
ruff check .

# Type check
mypy .
```

## Examples

### Without Schema (Draft Mode)

**Input:**
```json
{
  "question": "Show me all users from New York"
}
```

**Output:**
```json
{
  "sql": "SELECT * FROM <USERS_TABLE> WHERE <STATE_COLUMN> = 'New York' LIMIT 50",
  "status": "draft",
  "placeholders": [
    {"token": "<USERS_TABLE>", "meaning": "Table containing user data"},
    {"token": "<STATE_COLUMN>", "meaning": "Column containing state/location"}
  ],
  "clarifying_questions": [
    "What is the name of your users table?",
    "Which column contains the state information?"
  ]
}
```

### Modifying Statement (Review Required)

**Input:**
```json
{
  "question": "Delete all inactive accounts",
  "schema_metadata": {
    "tables": [{"name": "accounts", "columns": [{"name": "id"}, {"name": "status"}]}]
  }
}
```

**Output:**
```json
{
  "sql": "DELETE FROM accounts WHERE status = 'inactive'",
  "status": "review_required",
  "warnings": [
    "⚠️ This is a DELETE statement - it will permanently remove data when executed. Verify the WHERE clause carefully."
  ]
}
```

## Architecture Decisions

1. **Two LLM agents** - PlannerAgent (Groq/LLaMA 3.3 70b) + SqlWriterAgent (Local SQLCoder 7b)
2. **Deterministic policy gate** - No LLM for validation; faster, more predictable
3. **Single schema format** - JSON only, reduces complexity
4. **Placeholders over hallucination** - When schema is missing, use explicit `<PLACEHOLDER>` tokens
5. **Warnings over rejection** - Allow all SQL types with appropriate warnings

## Model Configuration

| Agent | Model | Provider |
|-------|-------|----------|
| PlannerAgent | llama-3.3-70b-versatile | Groq (cloud) |
| SqlWriterAgent | sqlcoder-7b-q4_0 | Local (ollama) |
