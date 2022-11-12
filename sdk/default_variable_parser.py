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
            return jsons.loads(config, dict)
        except DeserializationError:
            return None
