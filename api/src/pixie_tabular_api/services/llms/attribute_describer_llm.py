import logging
from typing import Optional

from langchain_core.messages import SystemMessage

from ..abstractclasses.llm import LLM


class AttributeDescriberLLM:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.system_prompt_template = """
        You are a helpful assistant specialized in describing attributes of a table.
        Given the following table name, table description and column name, please describe the specified column. When the column is categorical, the possible values are provided as well. Keep the description concise and informative, preferably in one sentence and do not mention the column name for brevity.
        TABLE NAME: {table_name}
        TABLE DESCRIPTION: {table_description}
        COLUMN NAME: {column_name}
        ATTRIBUTE VALUES: {attribute_values}
        =========
        Result:
        """

    def generate(
        self,
        table_name: str,
        table_description: str,
        column_name: str,
        attribute_values: list[str] | None,
    ) -> Optional[str]:
        """
        Generate a description of the attributes of a table using the LLM.
        Args:
            table_name (str): The name of the table.
            table_description (str): A brief description of the table.
            column_name (str): The name of the column to describe.
            attribute_values (list[str] | None): A list of values for the column, if applicable.
        Returns:
            Optional[str]: The generated description or None if an error occurs.
        """
        system_prompt = self.system_prompt_template.format(
            table_name=table_name,
            table_description=table_description,
            column_name=column_name,
            attribute_values=attribute_values,
        )
        system_message = SystemMessage(content=system_prompt)

        try:
            response = self.llm.invoke([system_message])
            if response is None:
                return None
            content = getattr(response, "content", None)
            if isinstance(content, list):
                return (
                    "\n".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict)
                    )
                    or None
                )
            return content
        except Exception as e:
            logging.error("Error generating attribute description: %s", str(e))
        return None
