from typing import List, Optional, Union, Dict, Any
import json
import pandas as pd
from agno.tools import Toolkit


class CsvTools(Toolkit):
    """
    Utility toolkit for CSV/XLSX files to inspect schemas, sample rows, and perform simple aggregations.
    """

    def __init__(self):
        super().__init__(name="csv_tools")
        self.register(self.list_columns)
        self.register(self.sample_rows)
        self.register(self.aggregate_sum)

    def _load_frame(self, file_path: str) -> pd.DataFrame:
        ext = (file_path or "").lower()
        if ext.endswith((".xlsx", ".xls")):
            return pd.read_excel(file_path)
        return pd.read_csv(file_path)

    def list_columns(self, file_path: str) -> List[str]:
        """Return the ordered list of column names for a CSV/XLSX file."""
        df = self._load_frame(file_path)
        return list(df.columns)

    def sample_rows(self, file_path: str, n: int = 5) -> str:
        """
        Return a JSON preview of the first n rows for quick inspection.
        """
        df = self._load_frame(file_path)
        preview = df.head(max(1, n)).to_dict(orient="records")
        return json.dumps(preview, default=str, indent=2)

    def aggregate_sum(
        self,
        file_path: str,
        group_by: Union[str, List[str]],
        value_col: Union[str, List[str]],
        date_col: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """
        Aggregate sums over one or more value columns, optionally filtered by a date range.
        - value_col: string for a single column OR list of columns to sum row-wise before grouping.
        Returns JSON rows with group keys and summed values.
        """
        df = self._load_frame(file_path)

        if date_col and (start_date or end_date) and date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            if start_date:
                df = df[df[date_col] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df[date_col] <= pd.to_datetime(end_date)]

        group_keys = [group_by] if isinstance(group_by, str) else list(group_by)

        # Normalize value columns
        if isinstance(value_col, list):
            cols = value_col
            missing = [c for c in cols if c not in df.columns]
            if missing:
                raise ValueError(f"Columns not found in {file_path}: {missing}")
            df["_agg_value"] = df[cols].apply(
                lambda row: pd.to_numeric(row, errors="coerce").fillna(0).sum(), axis=1
            )
            value_field = "_agg_value"
        else:
            if value_col not in df.columns:
                raise ValueError(f"Column not found in {file_path}: {value_col}")
            value_field = value_col
            df[value_field] = pd.to_numeric(df[value_field], errors="coerce")

        grouped = (
            df.groupby(group_keys, dropna=False)[value_field]
            .sum(numeric_only=True)
            .reset_index()
            .rename(columns={value_field: "sum"})
        )
        return grouped.to_json(orient="records", date_format="iso")
