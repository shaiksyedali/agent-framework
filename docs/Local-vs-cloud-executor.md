# Local vs Cloud Executor: Architecture Analysis

## Current Architecture

The FastAPI `azure_executor.py` orchestrates workflows locally, while **Supervisor** and **Executor** cloud agents are created in Azure OpenAI but never called.

```
┌─────────────────────────────────────────────────────────┐
│                     Current Flow                        │
├─────────────────────────────────────────────────────────┤
│  UI → FastAPI → azure_executor.py → Azure Functions     │
│         ↓                                               │
│    Planner Agent (cloud) → generates steps              │
│         ↓                                               │
│    azure_executor loops through steps:                  │
│      ├── RAG Agent (cloud) → consult_rag function       │
│      ├── SQL Agent (cloud) → execute_azure_sql function │
│      └── Response Generator (cloud)                     │
│         ↓                                               │
│    Job status updated → UI polls and displays           │
└─────────────────────────────────────────────────────────┘
```

---

## Why Local Executor Works Well

| Concern | How Local Executor Addresses It |
|---------|--------------------------------|
| **Error Visibility** | All tool calls wrapped in `try/except`. Exceptions are logged and returned in job's `status` and `logs`. UI displays exact failure point. |
| **Workflow Control** | Executor decides when to pause for HIL (`waiting_for_user`), when to retry, when to proceed. Logic is in ordinary Python—easy to extend. |
| **Single Source of Truth** | Job object holds step index, outputs, and context. UI only reads that object; no need to query multiple assistants. |
| **Extensibility** | Adding a new tool (e.g., local SQLite) only requires a new function and tool schema. No Azure OpenAI assistant changes needed. |
| **Debugging** | Full HTTP request/response visibility, custom retries, detailed error messages surfaced to HIL UI. |

---

## When Cloud Executor Makes Sense

| Benefit | What You'd Need |
|---------|-----------------|
| **LLM Reasoning Per Step** | Move step-execution into a tool the Executor assistant calls. LLM decides whether to retry, ask clarification, or continue. |
| **Built-in Tool Tracking** | Azure OpenAI auto-records tool inputs/outputs—useful for audit logs without extra instrumentation. |
| **Simpler Backend** | FastAPI only forwards job to executor assistant and polls status. Less custom orchestration code. |
| **Dynamic Tool Selection** | Executor decides at runtime which tool version (local vs Azure) to use based on step metadata. |

### Trade-offs

| Concern | Impact |
|---------|--------|
| **Error Granularity** | Rely on assistant's error messages and tool HTTP response. Need wrapper for UI-friendly errors. |
| **Latency** | Extra round-trip to Azure OpenAI per step (hundreds of ms each). |
| **State Management** | Job state must be persisted so assistant can read/write (via tool or thread memory with size limits). |
| **Schema Duplication** | Tool JSON defined in `create_azure_agents.py` must stay in sync if executor also needs them. |

---

## Decision: Keep Local Executor

**Rationale:**
1. Tight, deterministic error handling already in place
2. Full control over retries, HIL prompts, and logging
3. Workflows are relatively short (few steps)—extra cloud latency not justified
4. Easier to extend (add local SQL, new tools) without Azure changes

---

## Hybrid Option (Future)

If complex LLM-driven decisions are needed later:

1. **Layer executor agent on top of local executor**
   - `azure_executor` receives planner steps
   - Passes each step to Executor assistant as `execute_step` tool call
   - Executor runs step, calls backend tools (SQL, RAG)
   - `azure_executor` still catches HTTP failures, logs, updates job status
   - LLM reasoning becomes part of step output

2. **Add thin "LLM-decision" tools** for specific steps
   - E.g., `choose_sql_tool` returns `"local"` or `"azure"`
   - Best of both: deterministic handling + occasional LLM flexibility

---

## Checklist for Future Migration

| Item | Action |
|------|--------|
| **Tool Schemas** | Ensure executor agent has `execute_step`, `format_output`, `request_user_feedback` and any new decision tools |
| **State Persistence** | Expose `get_job_state`, `set_job_state` tools or use thread metadata |
| **Error Wrappers** | Wrap backend tools to return consistent `{success, data, error}` JSON |
| **HIL Integration** | Executor sets `job.status = "waiting_for_user"` on feedback request |
| **Logging** | Forward executor's `assistant_message` (thought process, tool use) to job logs |
| **Testing** | Verify errors bubble up correctly in both paths |

---

## Conclusion

**Current architecture with local `azure_executor` is the right choice** for this stage. It provides full observability, simpler debugging, and easier extensibility. Cloud executor can be layered on top later if LLM-driven orchestration becomes a requirement.
