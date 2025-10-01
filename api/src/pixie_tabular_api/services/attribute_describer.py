import logging
from typing import Any

import pandas as pd

from .llms.attribute_describer_llm import AttributeDescriberLLM


def describe_attributes(
    file_name: str,
    file_description: str,
    file_schema: dict[str, str],
    df: pd.DataFrame,
    attribute_describer_llm: AttributeDescriberLLM,
) -> dict[str, dict[str, Any]]:
    """
    Describe attributes based on the file schema and DataFrame.
    Returns a dictionary with attribute names as keys and their descriptions as values.
    """
    attribute_descriptions = {}

    for column_name, datatype in file_schema.items():
        logging.info(f"Describing attribute '{column_name}' with datatype '{datatype}'")
        attribute_dict = {}
        if column_name not in df.columns:
            attribute_descriptions[column_name] = {
                "type": "text",
                "description": attribute_describer_llm.generate(
                    table_name=file_name,
                    table_description=file_description,
                    column_name=column_name,
                    attribute_values=None,
                ),
            }
            continue

        if column_name in ["barcode", "naam", "beschrijving"]:
            attribute_dict["type"] = "text"
        elif datatype == "BOOLEAN":
            attribute_dict["type"] = "boolean"
        elif datatype != "TEXT":
            unique_values = df[column_name].dropna().unique()
            if len(unique_values) > 5:
                attribute_dict["type"] = "continuous"
                q1 = df[column_name].dropna().quantile(0.25)
                q3 = df[column_name].dropna().quantile(0.75)
                if pd.notna(q1):
                    attribute_dict["q1"] = float(q1)
                if pd.notna(q3):
                    attribute_dict["q3"] = float(q3)
            else:
                attribute_dict["type"] = "categorical"
                attribute_dict["values"] = unique_values.tolist()
        else:
            attribute_dict["type"] = "categorical"
            attribute_dict["values"] = df[column_name].dropna().unique().tolist()

        attribute_dict["description"] = attribute_describer_llm.generate(
            table_name=file_name,
            table_description=file_description,
            column_name=column_name,
            attribute_values=attribute_dict.get("values", None),
        )

        attribute_descriptions[column_name] = attribute_dict

    return attribute_descriptions
