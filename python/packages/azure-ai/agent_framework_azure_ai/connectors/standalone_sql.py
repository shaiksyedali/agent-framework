"""
Standalone SQL connector for Azure integration (no core package dependencies).
"""

import logging
import sqlite3
from typing import Any, Sequence

logger = logging.getLogger(__name__)


class SimpleSQLiteConnector:
    """Simple SQLite connector for testing without circular imports"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_schema(self) -> str:
        """Get database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Get all tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = cursor.fetchall()

            schema_parts = []

            for (table_name,) in tables:
                # Get columns for this table
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = cursor.fetchall()

                col_desc = []
                for _, col_name, col_type, not_null, default_val, pk in columns:
                    null_str = "NOT NULL" if not_null else "NULL"
                    pk_str = " PRIMARY KEY" if pk else ""
                    col_desc.append(f"  {col_name} {col_type} {null_str}{pk_str}")

                schema_parts.append(f"Table: {table_name}\n" + "\n".join(col_desc))

            return "\n\n".join(schema_parts)

        finally:
            conn.close()

    def run_query(
        self, query: str, params: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute SQL query"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name

        try:
            cursor = conn.cursor()

            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Check if query returns results
            if cursor.description is None:
                conn.commit()
                return [{"rows_affected": cursor.rowcount}]

            # Fetch all rows
            rows = cursor.fetchall()

            # Convert to list of dicts
            results = [dict(row) for row in rows]

            return results

        finally:
            conn.close()
