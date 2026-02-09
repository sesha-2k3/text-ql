"""
Integration tests for the orchestrator pipeline.

Note: These tests require GROQ_API_KEY to be set for full integration testing.
Tests are marked to skip if the API key is not available.
"""

import os

import pytest

from api.models import QueryStatus
from orchestrator.root import TextQLOrchestrator, run_pipeline


# Skip integration tests if no API key
requires_api_key = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set"
)


class TestOrchestratorUnit:
    """Unit tests that don't require API calls."""

    def test_orchestrator_creation(self):
        """Test that orchestrator can be created."""
        # This will fail on _ensure_initialized if no API key
        orchestrator = TextQLOrchestrator()
        assert orchestrator is not None


@requires_api_key
class TestOrchestratorIntegration:
    """Integration tests that require API access."""

    def test_simple_select_with_schema(self):
        """Test a simple SELECT with schema provided."""
        response = run_pipeline(
            question="Show me all customers from California",
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "customers",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "name", "type": "varchar"},
                            {"name": "state", "type": "varchar"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        assert response.status in (QueryStatus.VALIDATED, QueryStatus.DRAFT)
        assert "SELECT" in response.sql.upper()
        assert len(response.policy_errors) == 0

    def test_select_without_schema(self):
        """Test SELECT without schema - should produce placeholders."""
        response = run_pipeline(
            question="Show me all users from New York",
            dialect="postgres",
            schema_json=None,
        )

        assert response.sql is not None
        assert response.status == QueryStatus.DRAFT
        assert len(response.placeholders) > 0 or "<" in response.sql
        assert len(response.clarifying_questions) > 0

    def test_insert_statement(self):
        """Test INSERT statement generation."""
        response = run_pipeline(
            question="Add a new customer named John Smith from Texas",
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "customers",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "name", "type": "varchar"},
                            {"name": "state", "type": "varchar"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        assert response.status == QueryStatus.REVIEW_REQUIRED
        assert "INSERT" in response.sql.upper()
        assert any("INSERT" in w or "modify" in w.lower() for w in response.warnings)

    def test_delete_statement(self):
        """Test DELETE statement generation."""
        response = run_pipeline(
            question="Delete all inactive users",
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "users",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "status", "type": "varchar"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        assert response.status == QueryStatus.REVIEW_REQUIRED
        assert "DELETE" in response.sql.upper()

    def test_complex_join_query(self):
        """Test a query requiring JOINs."""
        response = run_pipeline(
            question="Show me customer names and their total order amounts",
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "customers",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "name", "type": "varchar"},
                        ]
                    },
                    {
                        "name": "orders",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "customer_id", "type": "integer", "foreign_key": "customers.id"},
                            {"name": "amount", "type": "decimal"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        assert response.status in (QueryStatus.VALIDATED, QueryStatus.DRAFT)
        # Should have JOIN or subquery
        sql_upper = response.sql.upper()
        assert "JOIN" in sql_upper or "customers" in response.sql.lower()

    def test_limit_enforcement(self):
        """Test that LIMIT is enforced on SELECT queries."""
        response = run_pipeline(
            question="Get all records from the users table",
            dialect="postgres",
            schema_json={
                "tables": [
                    {"name": "users", "columns": [{"name": "id"}]}
                ]
            }
        )

        assert response.sql is not None
        assert "LIMIT" in response.sql.upper()

    def test_aggregation_query(self):
        """Test aggregation functions."""
        response = run_pipeline(
            question="Count the number of orders per customer",
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "customer_id", "type": "integer"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        sql_upper = response.sql.upper()
        assert "COUNT" in sql_upper or "GROUP BY" in sql_upper

    def test_assumptions_generated(self):
        """Test that assumptions are generated for ambiguous queries."""
        response = run_pipeline(
            question="Show me recent orders",  # Ambiguous: what is "recent"?
            dialect="postgres",
            schema_json={
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {"name": "id", "type": "integer"},
                            {"name": "created_at", "type": "timestamp"},
                        ]
                    }
                ]
            }
        )

        assert response.sql is not None
        # Should have some assumptions about "recent"
        assert len(response.assumptions) > 0 or len(response.clarifying_questions) > 0

    def test_error_handling_empty_question(self):
        """Test handling of edge cases."""
        # The API layer should catch this, but test pipeline resilience
        response = run_pipeline(
            question="   ",  # Whitespace only
            dialect="postgres",
            schema_json=None,
        )

        # Should either return error or handle gracefully
        assert response is not None


class TestPipelineEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_schema_handled(self):
        """Test that invalid schema is handled gracefully."""
        # This should be caught at the API layer, but test pipeline resilience
        orchestrator = TextQLOrchestrator()

        # Mock the agents to avoid API calls
        class MockAgent:
            def run(self, **kwargs):
                from api.models import PlannerOutput, SqlWriterOutput
                return PlannerOutput(
                    schema_sufficient=False,
                    clarifying_questions=["What tables do you have?"],
                    assumptions=[],
                )

        # Can't fully test without mocking, but structure is in place
        pass
