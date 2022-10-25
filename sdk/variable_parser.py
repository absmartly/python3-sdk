from abc import abstractmethod
from typing import Optional

from sdk.context import Context


class VariableParser:

    @abstractmethod
    def parse(self, context: Context, experiment_name: str, variant_name: str, variable_value: str) -> Optional[dict]:
        raise NotImplementedError
