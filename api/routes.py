"""
API route handlers for text-ql.

Provides the /query endpoint and health checks.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from api.models import HealthResponse, QueryRequest, QueryResponse, QueryStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    from orchestrator import USING_ADK, USING_HYBRID
    if USING_HYBRID:
        version = "0.1.0-hybrid"  # Gemini + SQLCoder
    elif USING_ADK:
        version = "0.1.0-adk"    # Pure Gemini
    else:
        version = "0.1.0"        # Basic (Groq + Ollama)
    return HealthResponse(status="healthy", version=version)


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    """
    Convert natural language to SQL.
    """
    from orchestrator import run_pipeline_async, USING_ADK, USING_HYBRID
    
    logger.info(f"Received query: {request.question[:100]}...")
    logger.info(f"Using ADK: {USING_ADK}, Hybrid: {USING_HYBRID}")

    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    schema_json: dict[str, Any] | None = None
    if request.schema_metadata:
        schema_json = request.schema_metadata.model_dump()

    try:
        response = await run_pipeline_async(
            question=request.question,
            dialect=request.dialect,
            schema_json=schema_json,
        )
        logger.info(f"Query completed with status: {response.status}")
        return response

    except Exception as e:
        logger.exception(f"Pipeline error: {e}")
        return QueryResponse(
            sql=None,
            status=QueryStatus.ERROR,
            placeholders=[],
            warnings=[],
            clarifying_questions=[],
            assumptions=[],
            policy_errors=[f"Internal error: {str(e)}"],
        )


@router.get("/")
async def root() -> dict[str, str]:
    """Root endpoint with API information."""
    from orchestrator import USING_ADK, USING_HYBRID
    return {
        "name": "text-ql",
        "version": "0.1.0",
        "description": "Natural Language to SQL converter",
        "docs": "/docs",
        "using_adk": str(USING_ADK),
        "using_hybrid": str(USING_HYBRID),
        "pipeline": "Gemini + SQLCoder" if USING_HYBRID else ("Gemini" if USING_ADK else "Groq + Ollama"),
    }
