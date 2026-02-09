"""
Tests for the schema parser module.
"""

import pytest

from schema.models import Column, SchemaContext, Table
from schema.parser import SchemaParseError, parse_schema, validate_schema


class TestParseSchema:
    """Tests for schema parsing."""

    def test_empty_schema(self):
        result = parse_schema(None)
        assert result.is_empty
        assert len(result.tables) == 0

    def test_empty_tables_list(self):
        result = parse_schema({"tables": []})
        assert result.is_empty

    def test_single_table(self):
        data = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "integer", "primary_key": True},
                        {"name": "name", "type": "varchar"},
                    ]
                }
            ]
        }
        result = parse_schema(data)

        assert not result.is_empty
        assert len(result.tables) == 1
        assert result.tables[0].name == "users"
        assert len(result.tables[0].columns) == 2

    def test_multiple_tables(self):
        data = {
            "tables": [
                {"name": "users", "columns": [{"name": "id"}]},
                {"name": "orders", "columns": [{"name": "id"}]},
            ]
        }
        result = parse_schema(data)

        assert len(result.tables) == 2
        assert result.has_table("users")
        assert result.has_table("orders")

    def test_table_with_description(self):
        data = {
            "tables": [
                {
                    "name": "users",
                    "description": "User accounts",
                    "columns": [{"name": "id"}],
                }
            ]
        }
        result = parse_schema(data)

        assert result.tables[0].description == "User accounts"

    def test_column_with_all_fields(self):
        data = {
            "tables": [
                {
                    "name": "orders",
                    "columns": [
                        {
                            "name": "customer_id",
                            "type": "integer",
                            "description": "Reference to customer",
                            "primary_key": False,
                            "foreign_key": "customers.id",
                        }
                    ],
                }
            ]
        }
        result = parse_schema(data)
        col = result.tables[0].columns[0]

        assert col.name == "customer_id"
        assert col.type == "integer"
        assert col.description == "Reference to customer"
        assert col.primary_key is False
        assert col.foreign_key == "customers.id"

    def test_invalid_schema_not_dict(self):
        with pytest.raises(SchemaParseError) as exc_info:
            parse_schema("not a dict")
        assert "must be an object" in str(exc_info.value)

    def test_invalid_tables_not_list(self):
        with pytest.raises(SchemaParseError) as exc_info:
            parse_schema({"tables": "not a list"})
        assert "must be an array" in str(exc_info.value)

    def test_missing_table_name(self):
        with pytest.raises(SchemaParseError) as exc_info:
            parse_schema({"tables": [{"columns": []}]})
        assert "name" in str(exc_info.value)

    def test_missing_column_name(self):
        with pytest.raises(SchemaParseError) as exc_info:
            parse_schema({
                "tables": [
                    {"name": "users", "columns": [{"type": "int"}]}
                ]
            })
        assert "name" in str(exc_info.value)


class TestSchemaContext:
    """Tests for SchemaContext methods."""

    def test_has_table_case_insensitive(self):
        schema = SchemaContext(tables=(
            Table(name="Users", columns=(Column(name="id"),)),
        ))

        assert schema.has_table("Users")
        assert schema.has_table("users")
        assert schema.has_table("USERS")

    def test_has_column(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=(
                Column(name="id"),
                Column(name="name"),
            )),
        ))

        assert schema.has_column("users", "id")
        assert schema.has_column("users", "name")
        assert not schema.has_column("users", "email")
        assert not schema.has_column("orders", "id")

    def test_get_table(self):
        users_table = Table(name="users", columns=(Column(name="id"),))
        schema = SchemaContext(tables=(users_table,))

        assert schema.get_table("users") == users_table
        assert schema.get_table("USERS") == users_table
        assert schema.get_table("nonexistent") is None

    def test_get_table_names(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=()),
            Table(name="orders", columns=()),
        ))

        names = schema.get_table_names()
        assert "users" in names
        assert "orders" in names

    def test_to_prompt_string(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=(
                Column(name="id", type="integer", primary_key=True),
                Column(name="email", type="varchar"),
            )),
        ))

        prompt = schema.to_prompt_string()
        assert "DATABASE SCHEMA" in prompt
        assert "users" in prompt
        assert "id" in prompt
        assert "email" in prompt

    def test_empty_schema_prompt(self):
        schema = SchemaContext(tables=())
        assert "No schema provided" in schema.to_prompt_string()


class TestValidateSchema:
    """Tests for schema validation."""

    def test_valid_schema_no_warnings(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=(Column(name="id"),)),
        ))
        warnings = validate_schema(schema)
        assert len(warnings) == 0

    def test_duplicate_table_names(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=(Column(name="id"),)),
            Table(name="Users", columns=(Column(name="id"),)),
        ))
        warnings = validate_schema(schema)
        assert any("duplicate" in w.lower() for w in warnings)

    def test_duplicate_column_names(self):
        schema = SchemaContext(tables=(
            Table(name="users", columns=(
                Column(name="id"),
                Column(name="ID"),
            )),
        ))
        warnings = validate_schema(schema)
        assert any("duplicate" in w.lower() for w in warnings)

    def test_table_without_columns(self):
        schema = SchemaContext(tables=(
            Table(name="empty_table", columns=()),
        ))
        warnings = validate_schema(schema)
        assert any("no columns" in w.lower() for w in warnings)

    def test_invalid_foreign_key_format(self):
        schema = SchemaContext(tables=(
            Table(name="orders", columns=(
                Column(name="customer_id", foreign_key="invalid_format"),
            )),
        ))
        warnings = validate_schema(schema)
        assert any("invalid foreign key" in w.lower() for w in warnings)

    def test_foreign_key_to_nonexistent_table(self):
        schema = SchemaContext(tables=(
            Table(name="orders", columns=(
                Column(name="customer_id", foreign_key="customers.id"),
            )),
        ))
        warnings = validate_schema(schema)
        assert any("non-existent table" in w.lower() for w in warnings)

    def test_foreign_key_to_nonexistent_column(self):
        schema = SchemaContext(tables=(
            Table(name="customers", columns=(Column(name="id"),)),
            Table(name="orders", columns=(
                Column(name="customer_id", foreign_key="customers.nonexistent"),
            )),
        ))
        warnings = validate_schema(schema)
        assert any("non-existent column" in w.lower() for w in warnings)

    def test_valid_foreign_key(self):
        schema = SchemaContext(tables=(
            Table(name="customers", columns=(Column(name="id"),)),
            Table(name="orders", columns=(
                Column(name="customer_id", foreign_key="customers.id"),
            )),
        ))
        warnings = validate_schema(schema)
        # Should have no warnings about this FK
        assert not any("customers.id" in w for w in warnings)


class TestTable:
    """Tests for Table class."""

    def test_get_column(self):
        table = Table(name="users", columns=(
            Column(name="id"),
            Column(name="Name"),
        ))

        assert table.get_column("id") is not None
        assert table.get_column("name") is not None  # Case insensitive
        assert table.get_column("email") is None

    def test_to_prompt_string(self):
        table = Table(
            name="users",
            description="User accounts",
            columns=(
                Column(name="id", type="integer", primary_key=True),
            )
        )

        prompt = table.to_prompt_string()
        assert "users" in prompt
        assert "User accounts" in prompt
        assert "id" in prompt
        assert "PK" in prompt


class TestColumn:
    """Tests for Column class."""

    def test_to_prompt_string_minimal(self):
        col = Column(name="id")
        assert col.to_prompt_string() == "id"

    def test_to_prompt_string_with_type(self):
        col = Column(name="id", type="integer")
        prompt = col.to_prompt_string()
        assert "id" in prompt
        assert "integer" in prompt

    def test_to_prompt_string_with_pk(self):
        col = Column(name="id", primary_key=True)
        assert "PK" in col.to_prompt_string()

    def test_to_prompt_string_with_fk(self):
        col = Column(name="customer_id", foreign_key="customers.id")
        prompt = col.to_prompt_string()
        assert "FK" in prompt
        assert "customers.id" in prompt

    def test_to_prompt_string_with_description(self):
        col = Column(name="id", description="Primary identifier")
        assert "Primary identifier" in col.to_prompt_string()
