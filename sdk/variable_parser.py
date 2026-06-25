from abc import abstractmethod
from typing import Any, Optional


class VariableParser:

    @abstractmethod
    def parse(self,
              context,
              experiment_name: str,
              variant_name: str,
              variable_value: str) -> Optional[Any]:
        raise NotImplementedError
