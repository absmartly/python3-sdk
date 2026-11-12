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

    def evaluate_rules(self, rules: str, attributes: dict):
        """Return the first matching assignment-rule variant, or None."""
        try:
            raw = self.deserializer.deserialize(rules.encode("utf-8"), 0, len(rules.encode("utf-8")))
            if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
                return None
            for rule in raw["rules"]:
                if not isinstance(rule, dict) or rule.get("type") != "assign":
                    continue
                variant = rule.get("variant")
                if not isinstance(variant, int) or isinstance(variant, bool):
                    continue
                conditions = rule.get("conditions")
                if conditions is None:
                    return variant
                if not isinstance(conditions, (dict, list)):
                    continue
                try:
                    if self.json_expr.evaluate_boolean_expr(conditions, attributes) is True:
                        return variant
                except Exception:
                    continue
        except Exception:
            return None
        return None

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
