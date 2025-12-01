# Workflow Interface Roadmap

## Goal
Provide a short, actionable path to let users create, edit, and run agentic workflows with human-in-the-loop (HIL) controls. The recommendations below focus on what to build next after the core agents and orchestration scaffolding exist.

## Recommendation: start with a CLI, then layer the UI
- **Why a CLI first?** Faster iteration and easier debugging while the orchestration core, approval hooks, and connectors stabilize. It also lets you dogfood the streaming events and approval pauses without front-end dependencies.
- **When to add the UI?** Once the CLI proves the end-to-end path (plan → approval → SQL/RAG → reasoning → response) and the event contract is stable, build the UI views that consume those events.
- **Shared contract:** Both CLI and UI should consume the same workflow definition (persona, steps, data connectors) and the same stream of orchestration events so behavior stays consistent.

## Phase 1: CLI-first workflow creation and execution
- **Command surface**
  - `workflow init --name ...` to scaffold a workflow file with persona, prompts, steps, and data sources.
  - `workflow plan --file ...` to invoke the Planner agent, surface clarifications, and require user approval to lock the plan.
  - `workflow run --file ...` to execute via the orchestrator with streamed step events and approval pauses.
  - `workflow inspect --file ...` to print plan, data bindings, and last run artifacts (SQL, RAG snippets, responses).
- **Artifacts**
  - Store workflow definitions in JSON/YAML so UI can reuse them later.
  - Persist run logs and artifacts (plan, SQL text/results, RAG citations, reasoning notes) for inspection and for few-shot history.
- **HIL loop in CLI**
  - On planner proposals, SQL execution of non-SELECT/DDL/DML, and MCP calls, pause and prompt for `approve/deny/edit`.
  - Allow editing prompts/steps inline before re-running.

## Phase 2: UI that reuses the CLI contracts
- **Views to build**
  - **Workflow builder**: Form to edit workflow name, persona, steps, connectors; reuses the JSON/YAML schema. Shows planner clarifications and lets the user approve the plan.
  - **Data sources**: Panels to upload docs, configure DB engines (SQLite/DuckDB/Postgres), and register MCP servers with per-tool approval policies.
  - **Execution console**: Live stream of orchestrator events (plan, SQL text/results, RAG snippets, reasoning notes) with approval prompts and a chat sidebar for follow-ups.
  - **History & artifacts**: Table of past runs with links to SQL queries, results, citations, and plans for reuse as few-shot examples.
- **Event transport**
  - Standardize an event envelope (timestamp, step, agent, payload type, severity, approval state) so both CLI and UI render the same feed.
  - Support incremental streaming for long-running SQL/RAG calls and reasoning traces.

## Phase 3: Hardening and expansion
- **Reliability**: Add retry/backoff policies per tool, circuit breakers for failing connectors, and telemetry for approval latency and error rates.
- **Security**: Enforce allowlists for SQL/MCP tools, redact secrets in logs, and gate DDL/DML behind approvals by default.
- **Extensibility**: Document how to register custom agents and tools so domain teams can plug in (e.g., CAN decoder, fleet anomaly scorer) without changing the orchestrator.
- **Testing**: Provide contract tests for the event stream, planner approval flow, SQL adapters, and RAG retrieval paths.

## Decision checklist
- Do you need fast iteration and debugging? Start with the CLI.
- Do you need a UX for non-technical users? Build the UI once the CLI contracts are stable.
- Can both share the same workflow definition and event protocol? If yes, you get parity with less duplication.
