"""
Pytest configuration and fixtures for text-ql tests.
"""

import os
import sys

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_schema_json():
    """Sample schema JSON for testing."""
    return {
        "tables": [
            {
                "name": "customers",
                "description": "Customer accounts",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "name", "type": "varchar"},
                    {"name": "email", "type": "varchar"},
                    {"name": "state", "type": "varchar"},
                    {"name": "created_at", "type": "timestamp"},
                ]
            },
            {
                "name": "orders",
                "description": "Customer orders",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "customer_id", "type": "integer", "foreign_key": "customers.id"},
                    {"name": "total", "type": "decimal"},
                    {"name": "status", "type": "varchar"},
                    {"name": "order_date", "type": "date"},
                ]
            },
            {
                "name": "products",
                "columns": [
                    {"name": "id", "type": "integer", "primary_key": True},
                    {"name": "name", "type": "varchar"},
                    {"name": "price", "type": "decimal"},
                    {"name": "category", "type": "varchar"},
                ]
            }
        ]
    }


@pytest.fixture
def minimal_schema_json():
    """Minimal schema for simple tests."""
    return {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id"},
                    {"name": "name"},
                ]
            }
        ]
    }


@pytest.fixture
def sample_questions():
    """Sample natural language questions for testing."""
    return [
        "Show me all customers from California",
        "Count orders by status",
        "List the top 10 products by price",
        "Find customers who haven't ordered in 30 days",
        "What is the total revenue by month?",
        "Add a new customer named John",
        "Update all pending orders to processing",
        "Delete orders older than 2020",
    ]
