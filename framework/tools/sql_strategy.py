
from typing import Any, Dict, List, Optional
import json
import re
from datetime import datetime, date
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, Session

from agno.agent import Agent
from agno.tools import Toolkit
from agno.models.base import Model, Message
from agno.knowledge import Knowledge
from agno.utils.log import logger

class SQLStrategyTool(Toolkit):
    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        model: Optional[Model] = None,
        knowledge: Optional[Knowledge] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
        tables: Optional[Dict[str, Any]] = None,
        # Legacy args for backward compatibility
        max_retries: int = 4,
        sample_limit: int = 20,
        distinct_limit: int = 15,
        enable_cache: bool = True,
        allow_join_probe: bool = True,
        allow_filter_relaxation: bool = True,
        allow_question_on_empty: bool = True,
        max_date_backoff: int = 365,
        force_dialect: Optional[str] = None,
        robust_mode: bool = True,
        strict_filters_default: bool = True,
        **kwargs,
    ):
        super().__init__(name="sql_strategy", **kwargs)

        # 1. Initialize Database
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            _engine = create_engine(db_url)
        elif user and password and host and port and dialect:
            if schema is not None:
                _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}/{schema}")
            else:
                _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}")

        if _engine is None:
            raise ValueError("Could not build the database connection")

        self.db_engine: Engine = _engine
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)
        self.schema = schema
        self.tables = tables
        self.model = model
        self.knowledge = knowledge
        # Preserve last full result and query info for UI/state use
        self.last_full_result = None
        self.last_query_info: Dict[str, Any] = {}
        self.sample_limit = sample_limit
        
        # Register tools
        self.register(self.answer_question)
        self.register(self.list_tables)
        self.register(self.describe_table)
        # self.register(self.run_sql_query) # Hide raw SQL tool to enforce strategy usage

    def list_tables(self) -> str:
        """Get a list of table names in the database."""
        if self.tables is not None:
            return json.dumps(self.tables)
        try:
            inspector = inspect(self.db_engine)
            if self.schema:
                table_names = inspector.get_table_names(schema=self.schema)
            else:
                table_names = inspector.get_table_names()
            return json.dumps(table_names)
        except Exception as e:
            return f"Error getting tables: {e}"

    def describe_table(self, table_name: str) -> str:
        """Get the schema of a table."""
        try:
            inspector = inspect(self.db_engine)
            table_schema = inspector.get_columns(table_name, schema=self.schema)
            # Simplify schema output
            return json.dumps(
                [
                    {"name": column["name"], "type": str(column["type"])}
                    for column in table_schema
                ]
            )
        except Exception as e:
            return f"Error getting table schema: {e}"

    def _profile_table(self, table_name: str) -> str:
        """Profile a table to get row count and date ranges (agnostic)."""
        try:
            inspector = inspect(self.db_engine)
            columns = inspector.get_columns(table_name, schema=self.schema)
            
            # Identify time-like columns based on type string
            # Common SQL types: TIMESTAMP, DATE, DATETIME, TIME, etc.
            time_like_cols = []
            for col in columns:
                col_type = str(col["type"]).upper()
                if any(x in col_type for x in ["DATE", "TIME"]):
                    time_like_cols.append(col["name"])

            profile = {}
            
            with self.Session() as sess:
                # 1. Get Row Count
                count_query = text(f"SELECT COUNT(*) FROM {table_name}")
                profile["row_count"] = sess.execute(count_query).scalar()
                
                # 2. Get Min/Max for Time Columns
                if time_like_cols:
                    profile["time_columns"] = {}
                    # Construct a single query for efficiency if possible, or loop
                    # For safety and simplicity across dialects, we'll loop or build a combined query
                    # Combined query: SELECT MIN(c1), MAX(c1), MIN(c2), MAX(c2) ...
                    select_parts = []
                    for col in time_like_cols:
                        select_parts.append(f"MIN({col})")
                        select_parts.append(f"MAX({col})")
                    
                    if select_parts:
                        query_str = f"SELECT {', '.join(select_parts)} FROM {table_name}"
                        result = sess.execute(text(query_str)).fetchone()
                        
                        # Map results back to columns
                        for i, col in enumerate(time_like_cols):
                            min_val = result[i*2]
                            max_val = result[i*2+1]
                            profile["time_columns"][col] = {
                                "min": str(min_val) if min_val else None,
                                "max": str(max_val) if max_val else None
                            }
            
            return json.dumps(profile, default=str)
        except Exception as e:
            logger.warning(f"Error profiling table {table_name}: {e}")
            return "{}"

    def _run_sql_rows(self, query: str) -> List[Dict[str, Any]]:
        """Run SQL and return rows as list of dicts (full fidelity)."""
        with self.Session() as sess:
            result = sess.execute(text(query))
            return [dict(row._mapping) for row in result]

    def _run_sql_query(self, query: str) -> str:
        """Run a SQL query and return the result as JSON."""
        try:
            rows = self._run_sql_rows(query)
            return json.dumps(rows, default=str)
        except Exception as e:
            return f"Error executing SQL: {e}"

    def _preview_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Build a capped, stratified preview of rows for LLM/summary consumption.
        Dynamic cap: higher for narrow tables, lower for wide tables.
        Stratify on temporal or categorical keys when present to avoid biased previews.
        """
        if not rows:
            return []
        try:
            col_count = len(rows[0]) if isinstance(rows[0], dict) else 0
            base_cap = 10000 // max(1, col_count)
            cap = min(200, max(50, base_cap))
            # If very wide, tighten cap
            if col_count > 15:
                cap = min(cap, 100)

            # Attempt stratified sampling:
            temporal_keys = [k for k in rows[0].keys() if any(tok in k.lower() for tok in ["date", "time", "timestamp", "period", "month", "day"])]
            categorical_keys = [k for k in rows[0].keys() if any(tok in k.lower() for tok in ["id", "code", "type", "category", "class", "group"])]

            def stratify_by_key(data: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
                buckets: Dict[Any, List[Dict[str, Any]]] = {}
                for r in data:
                    buckets.setdefault(r.get(key), []).append(r)
                # sample roughly evenly across buckets
                per_bucket = max(1, cap // max(1, len(buckets)))
                sample: List[Dict[str, Any]] = []
                for _, vals in list(buckets.items())[:cap]:
                    sample.extend(vals[:per_bucket])
                    if len(sample) >= cap:
                        break
                return sample[:cap]

            # Prefer temporal stratification, else categorical, else head sample
            if temporal_keys:
                sampled = stratify_by_key(rows, temporal_keys[0])
            elif categorical_keys:
                sampled = stratify_by_key(rows, categorical_keys[0])
            else:
                sampled = rows[:cap]

            # Ensure cap enforcement
            return sampled[:cap]
        except Exception:
            return rows[:100]

    def _to_markdown_table(self, rows: List[Dict[str, Any]], max_rows: int = 50) -> str:
        """Render a simple Markdown table from rows (list of dicts), capped at max_rows."""
        if not rows:
            return ""
        try:
            subset = rows[:max_rows]
            headers = list(subset[0].keys())
            # Build header row
            header_line = "| " + " | ".join(headers) + " |"
            separator = "| " + " | ".join(["---"] * len(headers)) + " |"
            body_lines = []
            for r in subset:
                body_lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
            table = "\n".join([header_line, separator] + body_lines)
            if len(rows) > max_rows:
                table += f"\n\n_Preview showing {len(subset)} of {len(rows)} rows._"
            return table
        except Exception:
            return ""

    def _get_dialect_instructions(self) -> str:
        """Get dialect-specific instructions for SQL generation."""
        dialect = self.db_engine.dialect.name.lower()
        if "duckdb" in dialect:
            return (
                "You are using **DuckDB**. Use INTERVAL arithmetic (e.g., `ts > now() - INTERVAL 2 MONTH`). "
                "Do NOT use `DATEADD`/`DATE_ADD` signatures; prefer `ts >= latest_ts - INTERVAL 2 MONTH` or `ts >= date_trunc('month', now())`. "
                "Avoid window functions in WHERE clauses; compute aggregates in a CTE and join."
            )
        if "postgresql" in dialect or "postgres" in dialect:
            return (
                "You are using **PostgreSQL**. Use standard SQL with `INTERVAL` for date math (e.g., `ts > now() - INTERVAL '2 months'`). "
                "Use `date_trunc` for bucketing and avoid engine-specific functions from other dialects."
            )
        if "sqlite" in dialect:
            return (
                "You are using **SQLite**. Do NOT use `YEAR()`/`MONTH()`; instead use `strftime('%Y', col)` or `strftime('%m', col)`. "
                "Use `datetime('now', '-2 months')` style for relative filters."
            )
        return ""

    def _strip_trailing_semicolon(self, sql_query: str) -> str:
        return re.sub(r";+\s*$", "", sql_query.strip())

    def _parse_tables_used(self, sql_query: str) -> List[str]:
        """Best-effort extraction of table names from FROM/JOIN clauses."""
        try:
            candidates = re.findall(r"(?i)\bfrom\s+([^\s,;]+)|\bjoin\s+([^\s,;]+)", sql_query)
            tables = set()
            for a, b in candidates:
                tok = a or b
                tok = tok.strip()
                # strip aliases
                tok = tok.split(".")[-1]
                tok = tok.split()[0]
                if tok:
                    tables.add(tok)
            return list(tables)
        except Exception:
            return []

    def _parse_where_clause(self, sql_query: str) -> str:
        """Extract WHERE clause text for traceability."""
        try:
            m = re.search(r"(?is)\bwhere\b(.+?)(\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\blimit\b|$)", sql_query)
            if not m:
                return ""
            return m.group(1).strip()
        except Exception:
            return ""

    def _parse_date_windows(self, sql_query: str) -> Dict[str, Any]:
        """
        Heuristic to extract date window hints from WHERE clause (e.g., col between 'a' and 'b').
        """
        windows: Dict[str, Any] = {}
        where_txt = self._parse_where_clause(sql_query)
        if not where_txt:
            return windows
        try:
            # between pattern
            for m in re.finditer(r"(?i)([A-Za-z0-9_\.]+)\s+between\s+['\"]?([0-9\-: ]+)['\"]?\s+and\s+['\"]?([0-9\-: ]+)['\"]?", where_txt):
                col = m.group(1)
                windows[col] = {"min": m.group(2), "max": m.group(3)}
            # greater/less patterns
            for m in re.finditer(r"(?i)([A-Za-z0-9_\.]+)\s*>=\s*['\"]?([0-9\-: ]+)['\"]?", where_txt):
                col = m.group(1)
                win = windows.setdefault(col, {})
                win["min"] = m.group(2)
            for m in re.finditer(r"(?i)([A-Za-z0-9_\.]+)\s*<=\s*['\"]?([0-9\-: ]+)['\"]?", where_txt):
                col = m.group(1)
                win = windows.setdefault(col, {})
                win["max"] = m.group(2)
        except Exception:
            return windows
        return windows

    def _parse_group_by_columns(self, sql_query: str) -> List[str]:
        """Extract group by columns via simple regex."""
        try:
            m = re.search(r"(?is)\bgroup\s+by\b(.+?)(\bhaving\b|\border\s+by\b|\blimit\b|$)", sql_query)
            if not m:
                return []
            group_part = m.group(1)
            cols = [c.strip() for c in group_part.split(",") if c.strip()]
            return cols
        except Exception:
            return []

    def _parse_select_columns(self, sql_query: str) -> List[str]:
        """Extract select columns before FROM (best-effort)."""
        try:
            m = re.search(r"(?is)\bselect\b(.+?)\bfrom\b", sql_query)
            if not m:
                return []
            select_part = m.group(1)
            cols = [c.strip() for c in select_part.split(",") if c.strip()]
            return cols
        except Exception:
            return []

    def _ensure_group_keys_in_select(self, sql_query: str) -> str:
        """
        If query is aggregated (GROUP BY present) but grouping keys are not in SELECT,
        rewrite SELECT to include them for downstream payloads.
        """
        try:
            group_cols = self._parse_group_by_columns(sql_query)
            if not group_cols:
                return sql_query
            select_cols = self._parse_select_columns(sql_query)
            # Normalize aliases for comparison
            def normalize(col: str) -> str:
                col_no_alias = re.split(r"(?i)\bas\b", col)[0].strip()
                return col_no_alias
            select_norm = {normalize(c) for c in select_cols}
            missing = [c for c in group_cols if normalize(c) not in select_norm]
            if not missing:
                return sql_query
            # Rebuild SELECT with missing group cols prepended
            new_select_cols = missing + select_cols
            from_idx = re.search(r"(?is)\bfrom\b", sql_query)
            if not from_idx:
                return sql_query
            tail = sql_query[from_idx.start():]
            rebuilt = "SELECT " + ", ".join(new_select_cols) + " " + tail
            return rebuilt
        except Exception:
            return sql_query

    def _infer_column_kinds(self, rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        kinds = {"numeric": [], "categorical": [], "temporal": []}
        if not rows:
            return kinds
        first_row = rows[0]
        for col, val in first_row.items():
            if val is None:
                continue
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                kinds["numeric"].append(col)
            elif isinstance(val, (datetime, date)):
                kinds["temporal"].append(col)
            else:
                kinds["categorical"].append(col)
        return kinds

    def _summarize_numeric(self, base_sql: str, cols: List[str]) -> Dict[str, Any]:
        summaries: Dict[str, Any] = {}
        if not cols:
            return summaries
        dialect = self.db_engine.dialect.name.lower()
        for col in cols:
            # Build dialect-specific percentile/stddev functions
            stat_sql = (
                f"WITH base AS ({base_sql}) "
                f"SELECT COUNT({col}) AS count, MIN({col}) AS min, MAX({col}) AS max, "
                f"AVG({col}) AS avg FROM base"
            )
            percentile_sql = None
            stddev_sql = None
            if "duckdb" in dialect:
                percentile_sql = (
                    f"WITH base AS ({base_sql}) "
                    f"SELECT quantile({col}, 0.1) AS p10, quantile({col}, 0.5) AS p50, quantile({col}, 0.9) AS p90 FROM base"
                )
                stddev_sql = (
                    f"WITH base AS ({base_sql}) "
                    f"SELECT STDDEV_POP({col}) AS stddev FROM base"
                )
            elif "postgres" in dialect:
                percentile_sql = (
                    f"WITH base AS ({base_sql}) "
                    f"SELECT percentile_cont(0.1) WITHIN GROUP (ORDER BY {col}) AS p10, "
                    f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {col}) AS p50, "
                    f"percentile_cont(0.9) WITHIN GROUP (ORDER BY {col}) AS p90 FROM base"
                )
                stddev_sql = (
                    f"WITH base AS ({base_sql}) "
                    f"SELECT STDDEV_POP({col}) AS stddev FROM base"
                )
            try:
                rows = self._run_sql_rows(stat_sql)
                percentile_rows = []
                stddev_rows = []
                if percentile_sql:
                    percentile_rows = self._run_sql_rows(percentile_sql)
                if stddev_sql:
                    stddev_rows = self._run_sql_rows(stddev_sql)
                if rows:
                    summary_row = rows[0]
                    if percentile_rows:
                        summary_row.update(percentile_rows[0])
                    if stddev_rows:
                        summary_row.update(stddev_rows[0])
                    summaries[col] = summary_row
            except Exception as e:
                logger.warning(f"Numeric summary failed for {col}: {e}")
        return summaries

    def _summarize_categorical(self, base_sql: str, cols: List[str], total_count: int) -> Dict[str, Any]:
        summaries: Dict[str, Any] = {}
        if not cols or total_count <= 0:
            return summaries
        for col in cols:
            try:
                freq_sql = (
                    f"WITH base AS ({base_sql}) "
                    f"SELECT {col} AS value, COUNT(*) AS count FROM base "
                    f"GROUP BY {col} ORDER BY count DESC LIMIT 20"
                )
                rows = self._run_sql_rows(freq_sql)
                for r in rows:
                    r["share"] = (r.get("count", 0) or 0) / total_count
                summaries[col] = rows
            except Exception as e:
                logger.warning(f"Categorical summary failed for {col}: {e}")
        return summaries

    def _choose_time_bucket(self, min_dt: datetime, max_dt: datetime) -> str:
        span_days = (max_dt - min_dt).days if min_dt and max_dt else 0
        if span_days >= 180:
            return "month"
        if span_days >= 14:
            return "week"
        if span_days >= 2:
            return "day"
        return "hour"

    def _parse_dt(self, val: Any) -> Optional[datetime]:
        if isinstance(val, datetime):
            return val
        if isinstance(val, date):
            return datetime.combine(val, datetime.min.time())
        try:
            return datetime.fromisoformat(str(val).replace("Z", ""))
        except Exception:
            return None

    def _summarize_time(self, base_sql: str, cols: List[str]) -> Dict[str, Any]:
        summaries: Dict[str, Any] = {}
        if not cols:
            return summaries
        time_col = cols[0]
        dialect = self.db_engine.dialect.name.lower()
        try:
            # Get min/max to choose bucket
            bounds_sql = f"WITH base AS ({base_sql}) SELECT MIN({time_col}) AS min_v, MAX({time_col}) AS max_v FROM base"
            bounds = self._run_sql_rows(bounds_sql)
            if not bounds or bounds[0].get("min_v") is None or bounds[0].get("max_v") is None:
                return summaries
            min_dt = self._parse_dt(bounds[0]["min_v"])
            max_dt = self._parse_dt(bounds[0]["max_v"])
            if not min_dt or not max_dt:
                return summaries
            bucket = self._choose_time_bucket(min_dt, max_dt)
            if "duckdb" in dialect or "postgres" in dialect:
                bucket_expr = f"date_trunc('{bucket}', {time_col})"
            elif "sqlite" in dialect:
                # Simplify: use day buckets for sqlite; week/month handled via strftime
                if bucket == "hour":
                    bucket_expr = f"strftime('%Y-%m-%d %H:00', {time_col})"
                elif bucket == "day":
                    bucket_expr = f"strftime('%Y-%m-%d', {time_col})"
                elif bucket == "week":
                    bucket_expr = f"strftime('%Y-%W', {time_col})"
                else:
                    bucket_expr = f"strftime('%Y-%m-01', {time_col})"
            else:
                bucket_expr = time_col
            bucket_sql = (
                f"WITH base AS ({base_sql}) "
                f"SELECT {bucket_expr} AS bucket, COUNT(*) AS count "
                f"FROM base GROUP BY {bucket_expr} ORDER BY {bucket_expr} ASC LIMIT 200"
            )
            rows = self._run_sql_rows(bucket_sql)
            summaries[time_col] = {"bucket": bucket, "series": rows}
        except Exception as e:
            logger.warning(f"Time summary failed for {time_col}: {e}")
        return summaries

    def _derive_raw_from_aggregation(self, base_sql: str, limit: int = 200) -> Optional[str]:
        """
        Derive a raw (non-aggregated) preview query from an aggregation query by dropping GROUP/HAVING/ORDER/LIMIT.
        Keeps the same FROM/WHERE/JOIN clauses.
        """
        try:
            cleaned = self._strip_trailing_semicolon(base_sql)
            lower = cleaned.lower()
            from_idx = lower.find(" from ")
            if from_idx == -1:
                from_idx = lower.find("\nfrom ")
            if from_idx == -1:
                return None
            tail = cleaned[from_idx:]
            # Cut off at group/order/having/limit
            tail_core = re.split(r"(?i)\bgroup\s+by\b|\bhaving\b|\border\s+by\b|\blimit\b", tail)[0].strip()
            if not tail_core.lower().startswith("from"):
                tail_core = "FROM " + tail_core.lstrip()
            raw_sql = f"SELECT * {tail_core} LIMIT {limit}"
            return raw_sql
        except Exception as e:
            logger.warning(f"Raw derivation failed: {e}")
            return None

    def answer_question(self, question: str) -> str:
        """Answer a question using SQL queries."""
        if not self.model:
            return "Error: No LLM model configured for SQL Strategy."

        # 1. Get Context (Tables)
        tables_json = self.list_tables()
        
        # 2. Get Knowledge Context
        knowledge_context = ""
        if self.knowledge:
            try:
                search_results = self.knowledge.search(query=question, max_results=3)
                if search_results:
                    knowledge_context = "\n".join([r.content for r in search_results])
            except Exception as e:
                logger.warning(f"Knowledge search failed: {e}")

        # 3. Get Schema and Profile Data
        try:
            table_names = json.loads(tables_json)
            schema_text = ""
            for t in table_names:
                schema_text += f"Table: {t}\n{self.describe_table(t)}\n"
                # Profile the table
                profile = self._profile_table(t)
                schema_text += f"Data Profile: {profile}\n\n"
        except Exception:
            schema_text = tables_json

        # 4. Get Dialect Instructions
        dialect_instructions = self._get_dialect_instructions()

        prompt_with_schema = f"""
You are an expert SQL Data Analyst.
User Question: {question}

Database Schema and Data Profile:
{schema_text}

Relevant Context (from Knowledge Base):
{knowledge_context}

Instructions:
1. Generate a correct SQL query to answer the question.
2. Return ONLY the SQL query. No markdown, no explanation.
3. **CRITICAL**: Check the "Data Profile" for each table. 
   - The profile shows the time range of available data (min/max).
   - Use this to ground your temporal queries.
   - If the user asks for "recent" data or "last X months", calculate this relative to the **latest date** in the profile, rather than the current system time.
   - Only use `now()` or `CURRENT_DATE` if the user explicitly asks for "today" or "current time" AND the data supports it.
4. **Dialect-Specific Rules**:
   {dialect_instructions}
"""
        try:
            response = self.model.response(messages=[Message(role="user", content=prompt_with_schema)])
            sql_query = response.content.strip().replace("```sql", "").replace("```", "").strip()
            # Preserve grouping keys in SELECT for downstream consumption if aggregation detected
            sql_query = self._ensure_group_keys_in_select(sql_query)
            
            # Execute and retain full fidelity, with a rerun if grouping keys are missing from result
            result_rows: List[Dict[str, Any]] = []
            base_sql = self._strip_trailing_semicolon(sql_query)
            rerun_attempted = False
            while True:
                try:
                    # Traceability metadata
                    group_keys = self._parse_group_by_columns(base_sql)
                    tables_used = self._parse_tables_used(base_sql)
                    filters_applied = self._parse_where_clause(base_sql)
                    join_usage = "joins" if re.search(r"(?i)\bjoin\b", base_sql) else "single_table"
                    date_windows = self._parse_date_windows(base_sql)

                    result_rows = self._run_sql_rows(base_sql)
                    self.last_full_result = result_rows
                    self.last_query_info = {
                        "sql": base_sql,
                        "row_count": len(result_rows),
                        "tables_used": tables_used,
                        "filters_applied": filters_applied,
                        "join_usage": join_usage,
                        "date_windows": date_windows,
                        "group_keys": group_keys,
                    }
                    # If we have grouping keys but they are missing in the result columns, rerun once with enforced select
                    if (
                        group_keys
                        and result_rows
                        and not all(k in result_rows[0] for k in group_keys)
                        and not rerun_attempted
                    ):
                        rerun_attempted = True
                        base_sql = self._ensure_group_keys_in_select(base_sql)
                        continue
                    break
                except Exception as exec_err:
                    return f"Error executing SQL: {exec_err}"

            # Build preview for LLM synthesis
            result_preview = self._preview_rows(result_rows)
            result_preview_json = json.dumps(result_preview, default=str)
            preview_note = f"Preview ({len(result_preview)} of total {len(result_rows)} rows). Full results retained in state."
            md_renderer = getattr(self, "_to_markdown_table", None)
            if callable(md_renderer):
                preview_md = md_renderer(result_preview, max_rows=len(result_preview))
            else:
                preview_md = ""

            # Deterministic summaries with provenance
            col_kinds = self._infer_column_kinds(result_rows)
            numeric_summary = self._summarize_numeric(base_sql, col_kinds.get("numeric", []))
            categorical_summary = self._summarize_categorical(base_sql, col_kinds.get("categorical", []), len(result_rows))
            time_summary = self._summarize_time(base_sql, col_kinds.get("temporal", []))
            summaries = {
                "numeric": numeric_summary,
                "categorical": categorical_summary,
                "temporal": time_summary,
                "group_keys": self.last_query_info.get("group_keys", []),
                "scope": "aggregate_rows" if self._parse_group_by_columns(base_sql) else "overall",
            }
            if self.last_query_info.get("group_keys"):
                # Optional lightweight per-group frequency summary from aggregate rows
                key = self.last_query_info["group_keys"][0]
                freq = {}
                for r in result_rows:
                    freq[r.get(key)] = freq.get(r.get(key), 0) + 1
                total_groups = sum(freq.values())
                top_groups = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
                summaries["group_keys_summary"] = [
                    {"value": k, "count": v, "share": v / total_groups if total_groups else 0}
                    for k, v in top_groups
                ]
            self.last_query_info["summaries"] = summaries

            # If aggregation detected, derive a raw preview for transparency (not aggregated)
            raw_preview_rows: List[Dict[str, Any]] = []
            raw_preview_sql = None
            if any(tok in base_sql.lower() for tok in [" group by ", " avg(", " sum(", " count(", " having ", " min(", " max("]):
                raw_preview_sql = self._derive_raw_from_aggregation(base_sql, limit=self.sample_limit)
                if raw_preview_sql:
                    try:
                        raw_full = self._run_sql_rows(raw_preview_sql)
                        raw_preview_rows = self._preview_rows(raw_full)
                    except Exception as raw_err:
                        logger.warning(f"Raw preview execution failed: {raw_err}")
            if raw_preview_rows:
                self.last_query_info["raw_preview_sql"] = raw_preview_sql
                self.last_query_info["raw_preview_rows"] = raw_preview_rows
            if raw_preview_rows and callable(md_renderer):
                raw_preview_md = md_renderer(raw_preview_rows, max_rows=len(raw_preview_rows))
            else:
                raw_preview_md = ""
            
            # Synthesize
            metrics_payload = {
                "rows_returned": len(result_rows),
                "retries_used": 0,
                "tables_used": self.last_query_info.get("tables_used", []),
                "filters_applied": self.last_query_info.get("filters_applied", ""),
                "join_usage": self.last_query_info.get("join_usage", ""),
                "date_windows": self.last_query_info.get("date_windows", {}),
                "raw_sample_rows": len(raw_preview_rows),
                "is_aggregation": bool(raw_preview_rows),
                "computed_calculations": [],
                "full_data_available": True,
                "full_row_count": len(result_rows),
                "group_keys": self.last_query_info.get("group_keys", []),
            }

            synthesis_payload = {
                "question": question,
                "sql_query": sql_query,
                "metrics": metrics_payload,
                "aggregate_rows": result_preview,
                "raw_rows": raw_preview_rows,
                "aggregate_rows_markdown": preview_md,
                "raw_rows_markdown": raw_preview_md,
                "summaries": summaries,
                "preview_note": preview_note,
                "download_hint": "Full data retained server-side; UI should offer download/load-full-table using stored state (not LLM text).",
                "group_keys": self.last_query_info.get("group_keys", []),
                "render_hints": {
                    "primary_view": "aggregate_rows",
                    "raw_view_label": "Raw sample (not aggregated)",
                    "aggregate_view_label": "Aggregated results with grouping keys",
                    "preview_note": preview_note,
                },
            }

            synthesis_prompt = f"""
You are a Data Analyst. Synthesize a clear answer using the provided payload. Return VALID JSON with keys: thought_process, content, metrics, insights, visualizations, aggregate_rows, raw_rows. Do NOT add extra keys.

Payload: {json.dumps(synthesis_payload, default=str)}
"""
            try:
                final_response = self.model.response(messages=[Message(role="user", content=synthesis_prompt)])
                content = final_response.content
                parsed = json.loads(content.strip().replace("```json", "").replace("```", ""))
                if isinstance(parsed, dict):
                    # enforce metrics from payload (authoritative)
                    parsed["metrics"] = metrics_payload
                    parsed.setdefault("aggregate_rows", result_preview)
                    parsed.setdefault("raw_rows", raw_preview_rows)
                    # Flag preview-based content explicitly
                    if parsed.get("content") and len(result_preview) < len(result_rows):
                        parsed["content"] += "\n\n_Note: Insights are generated from the full results; displayed rows are a preview sample._"
                    parsed.setdefault("insights", [])
                    if len(result_preview) < len(result_rows):
                        parsed["insights"].append("Displayed rows are a preview sample; full dataset used for summaries and insights.")
                    # Ensure summaries reflect full data
                    parsed["summaries"] = summaries
                    return json.dumps(parsed, default=str)
            except Exception as synth_err:
                logger.warning(f"Synthesis failed, retrying with strict prompt: {synth_err}")

            # Strict retry on parse failure
            strict_prompt = f"""
Return VALID JSON only with keys: thought_process, content, metrics, insights, visualizations, aggregate_rows, raw_rows, summaries.
Use these values:
metrics: {json.dumps(metrics_payload, default=str)}
aggregate_rows: {json.dumps(result_preview, default=str)}
raw_rows: {json.dumps(raw_preview_rows, default=str)}
summaries: {json.dumps(summaries, default=str)}
preview_note: {preview_note}
aggregate_rows_markdown: {preview_md}
raw_rows_markdown: {raw_preview_md}
If preview rows are shown, add a note in content and insights indicating they are a preview sample and full data underlies summaries.
"""
            final_response = self.model.response(messages=[Message(role="user", content=strict_prompt)])
            return final_response.content
            
        except Exception as e:
            return f"Error processing request: {e}"
