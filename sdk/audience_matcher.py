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
        """Return the first matching assignment-rule action, or None."""
        try:
            encoded = rules.encode("utf-8")
            raw = self.deserializer.deserialize(encoded, 0, len(encoded))
            if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
                return None
            for rule in raw["rules"]:
                if not isinstance(rule, dict):
                    continue
                rule_type = rule.get("type")
                if rule_type not in ("assign", "split"):
                    continue
                conditions = rule.get("conditions")
                if conditions is not None:
                    if not isinstance(conditions, (dict, list)):
                        continue
                    try:
                        if self.json_expr.evaluate_boolean_expr(conditions, attributes) is not True:
                            continue
                    except Exception:
                        continue
                if rule_type == "assign":
                    variant = rule.get("variant")
                    if isinstance(variant, int) and not isinstance(variant, bool):
                        return {"type": "assign", "variant": variant}
                    continue
                percentages = rule.get("percentages")
                if isinstance(percentages, str):
                    try:
                        split = [float(part) / 100 for part in percentages.split("/")]
                        if split and all(value >= 0 for value in split) and abs(sum(split) - 1.0) < 1e-9:
                            return {"type": "split", "split": split}
                    except (TypeError, ValueError):
                        pass
        except Exception:
            return None
        return None

    def evaluate(self, audience: str, attributes: dict) -> Optional[Result]:
        bytes_arr = bytes(audience, encoding="utf-8")
        audience_map = self.deserializer.deserialize(bytes_arr, 0, len(bytes_arr))
        if audience_map is not None:
            if "filter" in audience_map:
                fl = audience_map["filter"]
                if type(fl) is dict or type(fl) is list:
                    expr = self.json_expr.evaluate_boolean_expr(fl, attributes)
                    return Result(expr)
        return None
