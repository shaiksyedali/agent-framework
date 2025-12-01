---
status: draft
contact: contributor
purpose: Gap analysis and next steps to make the HIL agentic framework production-ready
---

# HIL framework readiness and next steps

## Current coverage
- The specification defines Planner, SQL (DuckDB/SQLite/Postgres), RAG, Reasoning, Responder, and custom agents with human-in-the-loop approvals and streaming orchestration events driven from the UI inputs (workflow name, persona, knowledge sources, steps). It also outlines schema-aware SQL tooling, approval gating, and hybrid RAG + retry behavior.  
- The Python scaffolding implements configurable connectors for DuckDB/SQLite/Postgres with approval-aware schema/query tools, a toy retriever, and a `HilOrchestrator` that wires Planner → SQL → RAG → Reasoner → Responder agents.  
- The Next.js UI captures workflow definitions (persona, knowledge sources, SQL engine, steps), renders approvals, and displays mocked orchestration events and run history that mirror the expected streaming/approval contract.

## Gaps against the end-to-end requirements
- **Persistence and APIs**: No service layer to persist workflow definitions, run records, or chat history; no REST/SSE/WS endpoints for creating runs, streaming events, or posting approvals.
- **Real data plumbing**: Vector store ingestion/retrieval is stubbed; SQL few-shot retrieval from prior successes and evaluation/retry loops are not wired; MCP tools are not registered from UI inputs; Postgres connector requires DSN injection but is not validated via UI forms.
- **Safety and governance**: Approval maps are local to tools; there is no policy layer for per-tenant approval rules, audit logging, or secrets management for DB/MCP credentials.
- **Observability and QA**: No tracing/metrics around agent steps, retries, or tool errors; no regression tests for SQL generation correctness, RAG grounding quality, or UI-event contract compatibility.
- **UI-backend integration**: UI uses a mock client; it lacks connectors to real APIs for ingestion, run creation, streaming events, approval submission, and run history queries.

## Recommended next steps (priority ordered)
1) **Expose backend APIs and persistence**  
   - Add a workflow service that stores definitions (name, persona, prompts, data sources, steps) and returns a workflow ID.  
   - Implement run creation endpoints that pick engine-specific connectors, construct `HilOrchestrator`, and stream events over SSE/WS; add approval endpoints that unblock paused steps.  
   - Persist run state, artifacts (plan drafts, SQL text/results, RAG snippets), and chat history for follow-up questions.

2) **Finish data connectors and grounding**  
   - Wire vector store ingestion (chunking, embedding, metadata) and retrieval tools that emit cited snippets.  
   - Implement the SQL few-shot retrieval/evaluation loop using prior successful queries and schema metadata; add aggregation-aware raw-row fetches.  
   - Register MCP tools from UI inputs with approval policies; validate Postgres DSNs and allow optional write operations via approvals.

3) **Strengthen safety and governance**  
   - Centralize approval policy enforcement (DDL/DML, MCP actions) with audit logs; integrate secrets storage for DB/MCP credentials.  
   - Add guardrails for result leakage (row limits, PII redaction hooks) and calculator-based numeric checks to prevent LLM math errors.

4) **Observability and automated QA**  
   - Instrument agent steps, retries, and tool errors with tracing/metrics; ship structured logs for UI replay.  
   - Add test suites for SQL generation correctness, RAG grounding precision/recall, and contract tests for UI event envelopes.

5) **UI wiring and UX polish**  
   - Replace the mock client with real orchestrator APIs for run creation, streaming, approvals, and history.  
   - Add forms for DB/MCP credentials with validation, ingestion status indicators, and visualization of SQL/RAG outputs.  
   - Surface plan diffs/clarifications inline to keep the human-in-the-loop flow transparent.

6) **Custom agent onboarding**  
   - Provide a plug-in registry so domain-specific agents (e.g., CAN decoder, fleet anomaly scorer) can be attached per workflow with their own tools and approval policies.  
   - Extend the planner to recommend when to instantiate these agents based on workflow intent and data availability.

Tracking and delivering the steps above will make the framework holistic and capable of realizing the listed agentic workflows with human-in-the-loop oversight.
