from typing import Optional

from sdk.audience_deserializer import AudienceDeserializer
from sdk.jsonexpr.json_expr import JsonExpr


class Result:
    def __init__(self, result: bool):
        self.result = result


class AudienceMatcher:

    def __init__(self, deserializer: AudienceDeserializer):
        self.deserializer = deserializer
        self.json_expr = JsonExpr()

    def evaluate(self, audience: str, attributes: dict) -> Optional[Result]:
        bytes_arr = bytes(audience, encoding="utf-8")
        audience_map = self.deserializer.deserialize(bytes_arr,
                                                     0,
                                                     len(bytes_arr))
        if audience_map is not None:
            if "filter" in audience_map:
                fl = audience_map["filter"]
                if type(fl) is dict or type(fl) is list:
                    expr = self.json_expr.evaluate_boolean_expr(fl,
                                                                attributes)
                    return Result(expr)

        return None
