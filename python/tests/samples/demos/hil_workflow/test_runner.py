import importlib.util
import sys
import types
from enum import Enum
from pathlib import Path

import asyncio

import pytest


BASE_DIR = Path(__file__).resolve().parents[4] / "samples" / "demos" / "hil_workflow"


def _ensure_package(name: str, path: Path | None = None) -> types.ModuleType:
    module = sys.modules.get(name)
    if module is None:
        module = types.ModuleType(name)
        if path:
            module.__path__ = [str(path)]
        sys.modules[name] = module
    return module


def _install_runner_dependencies() -> None:
    _ensure_package("samples")
    _ensure_package("samples.demos")
    _ensure_package("samples.demos.hil_workflow", BASE_DIR)

    knowledge_module = types.ModuleType("samples.demos.hil_workflow.knowledge")

    class IngestDocument:  # pragma: no cover - stub
        def __init__(self, id: str, text: str, metadata: dict | None = None):
            self.id = id
            self.text = text
            self.metadata = metadata

    class VectorStore:  # pragma: no cover - stub
        def __init__(self, store):
            self.store = store

        def retriever_for(self, workflow_id: str):
            return None

        def ingest(self, workflow_id: str, documents):
            return None

    knowledge_module.IngestDocument = IngestDocument
    knowledge_module.VectorStore = VectorStore
    sys.modules["samples.demos.hil_workflow.knowledge"] = knowledge_module

    agent_framework_module = types.ModuleType("agent_framework")

    class MCPStreamableHTTPTool:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

    def ai_function(fn=None, **_):  # pragma: no cover - stub
        return fn

    agent_framework_module.MCPStreamableHTTPTool = MCPStreamableHTTPTool
    agent_framework_module.ai_function = ai_function
    sys.modules["agent_framework"] = agent_framework_module

    agents_module = types.ModuleType("agent_framework.agents")
    sys.modules["agent_framework.agents"] = agents_module
    sql_module = types.ModuleType("agent_framework.agents.sql")

    class SQLAgent:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

    class SQLExample:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

    sql_module.SQLAgent = SQLAgent
    sql_module.SQLExample = SQLExample
    sys.modules["agent_framework.agents.sql"] = sql_module

    data_module = types.ModuleType("agent_framework.data.connectors")

    class SQLApprovalPolicy:  # pragma: no cover - stub
        def __init__(self, approval_required=True, allow_writes=False, engine=None):
            self.approval_required = approval_required
            self.allow_writes = allow_writes
            self.engine = engine

    class DataConnectorError(Exception):
        pass

    class _BaseConnector:  # pragma: no cover - stub
        def __init__(self, approval_policy=None, **_):
            self.approval_policy = approval_policy or SQLApprovalPolicy()

    class CoreSQLiteConnector(_BaseConnector):
        pass

    class CorePostgresConnector(_BaseConnector):
        def __init__(self, connection_string=None, approval_policy=None, **kwargs):
            super().__init__(approval_policy=approval_policy, **kwargs)
            self.connection_string = connection_string

    class CoreDuckDBConnector(_BaseConnector):
        def __init__(self, database=None, approval_policy=None, **kwargs):
            super().__init__(approval_policy=approval_policy, **kwargs)
            self.database = database

    data_module.DataConnectorError = DataConnectorError
    data_module.SQLApprovalPolicy = SQLApprovalPolicy
    data_module.SQLiteConnector = CoreSQLiteConnector
    data_module.PostgresConnector = CorePostgresConnector
    data_module.DuckDBConnector = CoreDuckDBConnector
    sys.modules["agent_framework.data"] = types.ModuleType("agent_framework.data")
    sys.modules["agent_framework.data.connectors"] = data_module

    hil_module = types.ModuleType("agent_framework.hil_workflow")

    class Engine(Enum):  # pragma: no cover - stub
        SQLITE = "sqlite"
        POSTGRES = "postgres"
        DUCKDB = "duckdb"

    class SQLConnector:  # pragma: no cover - stub
        def __init__(self, approval_mode=None, allow_writes=False):
            self.approval_policy = types.SimpleNamespace(allow_writes=allow_writes)

    class SQLiteConnector(SQLConnector):
        pass

    class PostgresConnector(SQLConnector):
        def __init__(self, dsn=None, approval_mode=None, allow_writes=False):
            super().__init__(approval_mode=approval_mode, allow_writes=allow_writes)
            self.dsn = dsn

    class LocalRetriever:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            return lambda goal: "[]"

    class AzureEmbeddingRetriever(LocalRetriever):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    class WorkflowConfig:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

    class HilOrchestrator:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

        def build(self):
            class _Workflow:
                async def run_stream(self, *args, **kwargs):
                    if False:
                        yield None

            return _Workflow()

    hil_module.Engine = Engine
    hil_module.SQLConnector = SQLConnector
    hil_module.SQLiteConnector = SQLiteConnector
    hil_module.PostgresConnector = PostgresConnector
    hil_module.LocalRetriever = LocalRetriever
    hil_module.AzureEmbeddingRetriever = AzureEmbeddingRetriever
    hil_module.WorkflowConfig = WorkflowConfig
    hil_module.HilOrchestrator = HilOrchestrator
    sys.modules["agent_framework.hil_workflow"] = hil_module


def _load_module(name: str, module_name: str | None = None):
    module_name = module_name or f"samples.demos.hil_workflow.{name}"
    module_path = BASE_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


root_dir = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root_dir / "packages" / "core"))
sys.path.insert(0, str(root_dir))

_install_runner_dependencies()
persistence = _load_module("persistence")
runner = _load_module("runner")
async def _run_emit_redaction(tmp_path):
    store = persistence.Store(tmp_path / "events.sqlite")
    runner_instance = runner.Runner(store)
    run_id = "run-1"

    queue = runner_instance.bus.subscribe(run_id)
    detail = {
        "contact": {"email": "user@example.com", "phone": "+12345678901"},
        "notes": ["Call 5551234567", {"alt": "user@example.com"}],
        "metadata": {"channels": ("email user@example.com", "sms +19876543210")},
    }

    await runner_instance._emit(run_id, "status", "Reach out to user@example.com", detail)

    stored_events = store.list_events(run_id)
    assert len(stored_events) == 1
    expected_detail = {
        "contact": {"email": "[redacted]", "phone": "[redacted]"},
        "notes": ["Call [redacted]", {"alt": "[redacted]"}],
        "metadata": {"channels": ["email [redacted]", "sms [redacted]"]},
    }
    assert stored_events[0].detail == expected_detail
    assert stored_events[0].message == "Reach out to [redacted]"

    emitted_event = await queue.get()
    assert emitted_event.detail == expected_detail
    assert emitted_event.message == "Reach out to [redacted]"


def test_emit_redacts_detail(tmp_path):
    asyncio.run(_run_emit_redaction(tmp_path))


async def _run_emit_nested_redaction(tmp_path):
    store = persistence.Store(tmp_path / "events.sqlite")
    runner_instance = runner.Runner(store)
    run_id = "run-2"

    queue = runner_instance.bus.subscribe(run_id)

    detail = {
        "notifications": [
            {
                "methods": (
                    "email user@example.com",
                    [
                        "sms +12345678901",
                        {
                            "via": ("call 5551234567",),
                        },
                    ],
                )
            }
        ]
    }

    await runner_instance._emit(run_id, "status", "Contact +19876543210", detail)

    stored_events = store.list_events(run_id)
    assert len(stored_events) == 1
    expected_detail = {
        "notifications": [
            {
                "methods": [
                    "email [redacted]",
                    ["sms [redacted]", {"via": ["call [redacted]"]}],
                ]
            }
        ]
    }
    assert stored_events[0].detail == expected_detail
    assert stored_events[0].message == "Contact [redacted]"

    emitted_event = await queue.get()
    assert emitted_event.detail == expected_detail
    assert emitted_event.message == "Contact [redacted]"


def test_emit_redacts_nested_detail(tmp_path):
    asyncio.run(_run_emit_nested_redaction(tmp_path))
