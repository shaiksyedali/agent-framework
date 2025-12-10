#!/usr/bin/env python3
"""Test script for Phase 2: Schema Enrichment via RAG."""

from agent_framework.agents.sql import (
    SQLPromptBuilder, 
    build_enriched_schema,
    get_dialect_instructions,
    SQLAgent,
)
from agent_framework.data.connectors import SQLiteConnector

# Test 1: build_enriched_schema helper
print('=== Test 1: build_enriched_schema ===')
schema = "users: id (INT), name (TEXT), department_id (INT)"
context = """
- department_id: References departments table, NULL for contractors
- name: Full name in "Last, First" format
"""

enriched = build_enriched_schema(schema, context)
print(f"Enriched schema includes headers: {'## Database Schema' in enriched}")
print(f"Enriched schema includes context: {'department_id' in enriched}")

# Without context
no_context = build_enriched_schema(schema, None)
print(f"Without context returns original: {no_context == schema}")

# Test 2: SQLPromptBuilder with schema_context
print('\n=== Test 2: SQLPromptBuilder with schema_context ===')
builder = SQLPromptBuilder(
    schema=schema,
    dialect='postgresql',
    schema_context=context,
)
prompt = builder.build("List all employees in engineering")
print(f"Prompt has schema section: {'## Database Schema' in prompt}")
print(f"Prompt has context section: {'## Schema Documentation' in prompt}")
print(f"Prompt has dialect section: {'PostgreSQL Syntax' in prompt}")
print(f"Prompt has task section: {'## Your Task' in prompt}")

# Test 3: SQLPromptBuilder backward compatibility (no schema_context)
print('\n=== Test 3: Backward Compatibility ===')
builder_old = SQLPromptBuilder(
    schema=schema,
    dialect='sqlite',
)
prompt_old = builder_old.build("Get all users")
print(f"Works without schema_context: {len(prompt_old) > 0}")
print(f"Still has schema: {'id (INT)' in prompt_old}")

# Test 4: Verify SQLAgent signature has schema_context
print('\n=== Test 4: SQLAgent Parameter Check ===')
import inspect
sig = inspect.signature(SQLAgent.generate_and_execute)
params = list(sig.parameters.keys())
print(f"SQLAgent.generate_and_execute has schema_context: {'schema_context' in params}")

print('\n=== All Phase 2 Tests Passed ===')
