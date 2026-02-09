"""Orchestrator module for text-ql pipeline."""

# Try Hybrid ADK pipeline first (Gemini + SQLCoder), then pure ADK, then basic
USING_ADK = False
USING_HYBRID = False

try:
    from orchestrator.adk_hybrid_pipeline import (
        run_pipeline,
        run_pipeline_async,
        create_text_ql_pipeline,
        create_hybrid_pipeline,
        OllamaSqlCoderAgent,
    )
    USING_ADK = True
    USING_HYBRID = True
except ImportError as e:
    try:
        from orchestrator.adk_pipeline import (
            run_pipeline,
            run_pipeline_async,
            create_text_ql_pipeline,
        )
        create_hybrid_pipeline = None
        OllamaSqlCoderAgent = None
        USING_ADK = True
    except ImportError:
        from orchestrator.root import (
            run_pipeline,
            run_pipeline_async,
        )
        create_text_ql_pipeline = None
        create_hybrid_pipeline = None
        OllamaSqlCoderAgent = None

__all__ = [
    "run_pipeline",
    "run_pipeline_async",
    "create_text_ql_pipeline",
    "create_hybrid_pipeline",
    "OllamaSqlCoderAgent",
    "USING_ADK",
    "USING_HYBRID",
]
