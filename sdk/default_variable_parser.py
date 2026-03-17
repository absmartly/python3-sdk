from typing import Optional
import json

from sdk.context import Context
from sdk.variable_parser import VariableParser


class DefaultVariableParser(VariableParser):

    def parse(self,
              context: Context,
              experiment_name: str,
              variant_name: str,
              config: str) -> Optional[dict]:
        try:
            result = json.loads(config)
            return result
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in variant config: {e}") from e
