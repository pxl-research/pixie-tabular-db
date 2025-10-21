"""Simple attribute type analysis."""

from typing import Any

import pandas as pd

# Column names that should always be treated as plain text,
# regardless of their statistical properties
TEXT_ONLY_COLUMNS = frozenset(["barcode", "naam", "beschrijving"])


def analyze_attribute(
    column_name: str, df: pd.DataFrame, datatype: str
) -> dict[str, Any]:
    """
    Analyze a single attribute and return its metadata.

    Args:
        column_name: The name of the column to analyze.
        df: The DataFrame containing the column.
        datatype: The datatype from the schema (e.g., "TEXT", "BOOLEAN", "INTEGER").

    Returns:
        A dictionary with type information and optional values/quantiles.
    """
    if column_name not in df.columns:
        return {"type": "text"}

    # Special cases for text fields
    if column_name in TEXT_ONLY_COLUMNS:
        return {"type": "text"}

    if datatype == "BOOLEAN":
        return {"type": "boolean"}

    if datatype == "TEXT":
        values = df[column_name].dropna().unique().tolist()
        return {"type": "categorical", "values": values}

    # Numeric types
    unique_values = df[column_name].dropna().unique()
    if len(unique_values) <= 5:
        return {"type": "categorical", "values": unique_values.tolist()}

    # Continuous numeric
    result: dict[str, Any] = {"type": "continuous"}
    q1 = df[column_name].dropna().quantile(0.25)
    q3 = df[column_name].dropna().quantile(0.75)
    if pd.notna(q1):
        result["q1"] = float(q1)
    if pd.notna(q3):
        result["q3"] = float(q3)
    return result
