"""Schema-aware SQL generation and execution helpers."""

from __future__ import annotations

import ast
import inspect
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Sequence

from agent_framework.data.connectors import DataConnectorError, SQLApprovalPolicy, SQLConnector
from agent_framework.observability import get_meter, get_tracer


logger = logging.getLogger(__name__)
tracer = get_tracer(__name__)
meter = get_meter(__name__)

sql_attempt_counter = meter.create_counter(
    name="agent_sql_generation_attempts_total",
    description="Count of SQL generation/execution attempts from SQLAgent",
)
sql_retry_counter = meter.create_counter(
    name="agent_sql_retries_total",
    description="Count of retries performed by SQLAgent",
)
sql_failure_counter = meter.create_counter(
    name="agent_sql_failures_total",
    description="Count of failed SQL attempts (including validator failures)",
)


@dataclass
class SQLExample:
    """Historical example used to prime SQL generation."""

    question: str
    sql: str
    answer: Any | None = None


@dataclass
class SQLAttempt:
    """A single SQL generation/execution attempt."""

    sql: str | None
    rows: list[dict[str, Any]] | None = None
    raw_rows: list[dict[str, Any]] | None = None
    error: str | None = None
    feedback: str | None = None


@dataclass
class SQLExecutionResult:
    """Final result including generation history."""

    sql: str | None
    rows: list[dict[str, Any]] | None
    raw_rows: list[dict[str, Any]] | None
    attempts: list[SQLAttempt] = field(default_factory=list)


class SQLPromptBuilder:
    """Build prompts with schema and few-shot guidance."""

    def __init__(
        self,
        *,
        schema: str,
        history: Sequence[SQLExample] | None = None,
        max_examples: int = 3,
    ) -> None:
        self._schema = schema
        self._history = list(history or [])[:max_examples]
        self._max_examples = max_examples

    def build(self, goal: str, feedback: str | None = None) -> str:
        parts: list[str] = [
            "You are an expert data analyst that produces syntactically correct SQL.",
            "Use the following database schema to ground your query:",
            self._schema or "<unknown schema>",
        ]

        if self._history:
            examples = self._history[: self._max_examples]
            rendered = []
            for example in examples:
                rendered.append(
                    "Question: "
                    + example.question
                    + "\nSQL: "
                    + example.sql
                    + (f"\nAnswer: {example.answer}" if example.answer is not None else "")
                )
            parts.append("Previous solutions to emulate:\n" + "\n\n".join(rendered))

        if feedback:
            parts.append(f"Incorporate this feedback from earlier attempts: {feedback}")

        parts.append(
            "Respond with a single SQL statement that answers the request."
            " Avoid DDL/DML unless explicitly requested."
        )
        parts.append(f"User request: {goal}")
        return "\n\n".join(parts)


class SQLAgent:
    """Generate and execute SQL with retries and safety features."""

    def __init__(
        self,
        *,
        llm: Callable[[str], Awaitable[str] | str] | None = None,
        few_shot_examples: Sequence[SQLExample] | None = None,
        few_shot_limit: int = 3,
    ) -> None:
        self._llm = llm or (lambda _: "SELECT 1 as result")
        self._few_shot_examples = list(few_shot_examples or [])
        self._few_shot_limit = few_shot_limit

    async def generate_and_execute(
        self,
        goal: str,
        connector: SQLConnector,
        *,
        schema: str | None = None,
        history: Sequence[SQLExample] | None = None,
        max_attempts: int = 3,
        validator: Callable[[list[dict[str, Any]]], bool] | None = None,
        fetch_raw_after_aggregation: bool = True,
        enable_calculator_fallback: bool = True,
        allow_writes: bool | None = None,
        row_limit: int | None = None,
        redaction_hook: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        verify_numeric_results: bool = True,
    ) -> SQLExecutionResult:
        """Generate SQL for a goal, run it, and retry on errors or invalid answers."""

        attempts: list[SQLAttempt] = []
        feedback: str | None = None
        allow_writes = allow_writes if allow_writes is not None else getattr(
            connector.approval_policy, "allow_writes", True
        )
        enforced_row_limit = row_limit if row_limit is not None else connector.approval_policy.row_limit
        schema_text = schema or connector.get_schema()
        examples: list[SQLExample] = list(self._few_shot_examples)
        if history:
            examples.extend(history)
        prompt_builder = SQLPromptBuilder(
            schema=schema_text,
            history=examples,
            max_examples=self._few_shot_limit,
        )

        for attempt_index in range(max_attempts):
            prompt = prompt_builder.build(goal, feedback=feedback)
            with tracer.start_as_current_span(
                "sql.generate_and_execute",
                attributes={"goal": goal, "attempt": attempt_index + 1},
            ) as span:
                sql_attempt_counter.add(1, {"goal": goal})
                if attempt_index:
                    sql_retry_counter.add(1, {"goal": goal})

                raw_response = await self._invoke_llm(prompt)
                candidate_sql = self._extract_sql(raw_response)
                logger.info(
                    "sql.attempt.start",
                    extra={
                        "event_name": "sql_attempt",
                        "attempt": attempt_index + 1,
                        "goal": goal,
                        "candidate_sql": candidate_sql,
                    },
                )

                if enable_calculator_fallback and not self._looks_like_sql(candidate_sql):
                    try:
                        calculator_value = self._evaluate_math_expression(candidate_sql)
                        attempt = SQLAttempt(sql=None, rows=[{"result": calculator_value}], raw_rows=None)
                        attempts.append(attempt)
                        span.set_attribute("sql.fallback", "calculator")
                        return SQLExecutionResult(sql=None, rows=attempt.rows, raw_rows=None, attempts=attempts)
                    except Exception as exc:  # pragma: no cover - defensive
                        feedback = f"Calculator fallback failed: {exc}"
                        attempts.append(SQLAttempt(sql=None, rows=None, raw_rows=None, error=str(exc), feedback=feedback))
                        sql_failure_counter.add(1, {"goal": goal, "reason": "calculator_fallback"})
                        continue

                if not candidate_sql:
                    feedback = "No SQL statement was produced."
                    attempts.append(SQLAttempt(sql=None, rows=None, raw_rows=None, error=feedback, feedback=feedback))
                    sql_failure_counter.add(1, {"goal": goal, "reason": "no_sql"})
                    continue

                if allow_writes is False and connector.approval_policy.is_risky(candidate_sql):
                    reason = "Write operations are disabled by policy"
                    attempts.append(SQLAttempt(sql=candidate_sql, rows=None, raw_rows=None, error=reason, feedback=reason))
                    sql_failure_counter.add(1, {"goal": goal, "reason": "writes_blocked"})
                    continue

                if self._requires_blocking(connector.approval_policy, candidate_sql):
                    reason = "Approval required for risky statements"
                    attempts.append(SQLAttempt(sql=candidate_sql, rows=None, raw_rows=None, error=reason, feedback=reason))
                    sql_failure_counter.add(1, {"goal": goal, "reason": "approval_block"})
                    raise DataConnectorError(reason)

                try:
                    rows = connector.run_query(candidate_sql)
                    rows = connector.approval_policy.apply_row_limit(rows)
                    if enforced_row_limit and enforced_row_limit > 0:
                        rows = rows[:enforced_row_limit]
                    if redaction_hook:
                        rows = redaction_hook(rows)
                    if verify_numeric_results:
                        self._verify_numeric_rows(rows)
                except DataConnectorError as exc:
                    feedback = f"Error executing SQL: {exc}"
                    attempts.append(SQLAttempt(sql=candidate_sql, rows=None, raw_rows=None, error=str(exc), feedback=feedback))
                    sql_failure_counter.add(1, {"goal": goal, "reason": "execution_error"})
                    span.record_exception(exc)
                    continue

                if validator and not validator(rows):
                    feedback = "Validator rejected the result as incorrect"
                    attempts.append(SQLAttempt(sql=candidate_sql, rows=rows, raw_rows=None, error=feedback, feedback=feedback))
                    sql_failure_counter.add(1, {"goal": goal, "reason": "validator_rejection"})
                    continue

                raw_rows: list[dict[str, Any]] | None = None
                if fetch_raw_after_aggregation and self._has_aggregation(candidate_sql):
                    raw_query = self._derive_raw_query(candidate_sql)
                    if raw_query:
                        try:
                            raw_rows = connector.run_query(raw_query)
                            raw_rows = connector.approval_policy.apply_row_limit(raw_rows)
                            if enforced_row_limit and enforced_row_limit > 0:
                                raw_rows = raw_rows[:enforced_row_limit]
                            if redaction_hook:
                                raw_rows = redaction_hook(raw_rows)
                        except DataConnectorError:  # pragma: no cover - fallback
                            raw_rows = None

                attempt = SQLAttempt(sql=candidate_sql, rows=rows, raw_rows=raw_rows)
                attempts.append(attempt)
                logger.info(
                    "sql.attempt.complete",
                    extra={
                        "event_name": "sql_attempt_complete",
                        "attempt": attempt_index + 1,
                        "goal": goal,
                        "candidate_sql": candidate_sql,
                        "rows": rows,
                    },
                )
                return SQLExecutionResult(sql=candidate_sql, rows=rows, raw_rows=raw_rows, attempts=attempts)

        raise DataConnectorError("Failed to generate valid SQL after retries")

    async def _invoke_llm(self, prompt: str) -> str:
        response = self._llm(prompt)
        if inspect.isawaitable(response):
            response = await response
        return str(response)

    @staticmethod
    def _extract_sql(response: str) -> str:
        code_block = re.search(r"```(?:sql)?\s*(.*?)```", response, flags=re.IGNORECASE | re.DOTALL)
        if code_block:
            response = code_block.group(1)
        cleaned = response.strip()
        cleaned = cleaned.rstrip(";")
        return cleaned

    @staticmethod
    def _looks_like_sql(text: str) -> bool:
        lowered = text.lower().strip()
        return bool(lowered) and any(keyword in lowered for keyword in ("select", "insert", "update", "delete", "with"))

    @staticmethod
    def _has_aggregation(sql: str) -> bool:
        lowered = sql.lower()
        return any(keyword in lowered for keyword in ("group by", "count(", "sum(", "avg(", "min(", "max("))

    @staticmethod
    def _derive_raw_query(sql: str, *, limit: int = 25) -> str | None:
        table_match = re.search(r"from\s+([\w\.]+)", sql, flags=re.IGNORECASE)
        if not table_match:
            return None
        table = table_match.group(1)
        where_match = re.search(r"where\s+(.+?)(group by|order by|limit|$)", sql, flags=re.IGNORECASE | re.DOTALL)
        where_clause = f" WHERE {where_match.group(1).strip()}" if where_match else ""
        return f"SELECT * FROM {table}{where_clause} LIMIT {limit}"

    @staticmethod
    def _requires_blocking(policy: SQLApprovalPolicy, sql: str) -> bool:
        return policy.is_risky(sql) and not policy.should_request_approval(sql)

    @staticmethod
    def _evaluate_math_expression(expression: str) -> float:
        node = ast.parse(expression, mode="eval").body
        allowed_nodes = (
            ast.Expression,
            ast.BinOp,
            ast.UnaryOp,
            ast.Num,
            ast.Constant,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.Pow,
            ast.Mod,
            ast.USub,
        )

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Num):
                return float(node.n)
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
                return -_eval(node.operand)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)):
                left = _eval(node.left)
                right = _eval(node.right)
                return float({
                    ast.Add: left + right,
                    ast.Sub: left - right,
                    ast.Mult: left * right,
                    ast.Div: left / right,
                    ast.Pow: left ** right,
                    ast.Mod: left % right,
                }[type(node.op)])
            raise ValueError("Unsupported expression for calculator fallback")

        if not all(isinstance(n, allowed_nodes) or isinstance(n, ast.Load) for n in ast.walk(node)):
            raise ValueError("Unsafe expression")
        return _eval(node)

    @staticmethod
    def _verify_numeric_rows(rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        first_row = rows[0]
        if len(first_row) != 1:
            return
        value = next(iter(first_row.values()))
        if isinstance(value, (int, float)):
            return
        if isinstance(value, str):
            try:
                SQLAgent._evaluate_math_expression(value)
            except ValueError as exc:  # pragma: no cover - validation guardrail
                raise DataConnectorError(f"Numeric verification failed: {exc}") from exc


__all__ = [
    "SQLAgent",
    "SQLAttempt",
    "SQLExample",
    "SQLExecutionResult",
    "SQLPromptBuilder",
]
