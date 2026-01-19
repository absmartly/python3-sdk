from typing import Optional

import jsons
from jsons import DeserializationError

from sdk.context import Context
from sdk.variable_parser import VariableParser


class DefaultVariableParser(VariableParser):

    def parse(self,
              context: Context,
              experiment_name: str,
              variant_name: str,
              config: str) -> Optional[dict]:
        try:
            import json as stdlib_json
            result = stdlib_json.loads(config)
            if isinstance(result, dict):
                return result
            return result
        except (DeserializationError, Exception):
            return None
