from typing import Optional
import json
import logging

import jsons
from jsons import DeserializationError

from sdk.context import Context
from sdk.variable_parser import VariableParser

logger = logging.getLogger(__name__)


class DefaultVariableParser(VariableParser):

    def parse(self,
              context: Context,
              experiment_name: str,
              variant_name: str,
              config: str) -> Optional[dict]:
        try:
            result = json.loads(config)
            if isinstance(result, dict):
                return result
            return result
        except json.JSONDecodeError as e:
            error_msg = f"Failed to parse variant config for {experiment_name}/{variant_name}: {e}"
            logger.error(error_msg)
            if context.event_logger:
                try:
                    from sdk.json.event_type import EventType
                    context.event_logger.handle_event(EventType.ERROR, error_msg)
                except Exception:
                    pass
            raise ValueError(f"Invalid JSON in variant config: {e}") from e
        except Exception as e:
            error_msg = f"Unexpected error parsing variant {experiment_name}/{variant_name}: {e}"
            logger.error(error_msg)
            if context.event_logger:
                try:
                    from sdk.json.event_type import EventType
                    context.event_logger.handle_event(EventType.ERROR, error_msg)
                except Exception:
                    pass
            raise
