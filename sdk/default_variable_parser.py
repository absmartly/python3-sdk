from typing import Any, Optional
import json

from sdk.context import Context
from sdk.variable_parser import VariableParser


class DefaultVariableParser(VariableParser):

    def parse(self,
              context: Context,
              experiment_name: str,
              variant_name: str,
              config: str) -> Optional[Any]:
        # Invalid JSON returns None, as in v0.2.4; Context logs an ERROR
        # event for it and treats the variant as having no variables.
        try:
            return json.loads(config)
        except (TypeError, ValueError):
            return None
