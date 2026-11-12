import logging
import math
import re
from typing import Optional

from sdk.audience_deserializer import AudienceDeserializer
from sdk.jsonexpr.json_expr import JsonExpr

logger = logging.getLogger(__name__)


class Result:
    def __init__(self, result: bool):
        self.result = result


class RuleAction:
    def __init__(self, variant=None, split=None):
        self.variant = variant
        self.split = split


class AudienceMatcher:

    def __init__(self, deserializer: AudienceDeserializer):
        self.deserializer = deserializer
        self.json_expr = JsonExpr()

    def _deserialize(self, text):
        if not isinstance(text, str) or not text:
            return None
        try:
            bytes_arr = bytes(text, encoding="utf-8")
            return self.deserializer.deserialize(bytes_arr, 0, len(bytes_arr))
        except Exception:
            return None

    def evaluate(self, audience: str, attributes: dict) -> Optional[Result]:
        audience_map = self._deserialize(audience)
        if isinstance(audience_map, dict):
            fl = audience_map.get("filter")
            if isinstance(fl, (dict, list)):
                try:
                    return Result(self.json_expr.evaluate_boolean_expr(fl, attributes))
                except Exception:
                    logger.warning("Failed to evaluate audience filter; treating it as a mismatch")
                    return Result(False)
        return None

    def evaluate_rules(self, assignment_rules, environment, attributes):
        rules_map = self._deserialize(assignment_rules)
        if not isinstance(rules_map, dict) or not isinstance(rules_map.get("rules"), list):
            return None
        for rule in rules_map["rules"]:
            if not isinstance(rule, dict):
                continue
            action = self._rule_action(rule)
            if action is None:
                continue
            environments = rule.get("environments")
            if environments is not None:
                if not isinstance(environments, list):
                    continue
                if environments and (environment is None or environment not in environments):
                    continue
            conditions = rule.get("conditions")
            if conditions is None:
                return action
            if not isinstance(conditions, dict):
                continue
            try:
                if self.json_expr.evaluate_boolean_expr(conditions, attributes):
                    return action
            except Exception:
                logger.warning("Failed to evaluate assignment rule conditions")
        return None

    @staticmethod
    def _rule_action(rule):
        if rule.get("type") == "assign":
            variant = rule.get("variant")
            if isinstance(variant, bool) or not isinstance(variant, (int, float)) \
                    or not math.isfinite(variant) or variant < 0 \
                    or int(variant) != variant:
                return None
            return RuleAction(variant=int(variant))
        if rule.get("type") != "split" or not isinstance(rule.get("percentages"), str):
            return None
        values = []
        for part in rule["percentages"].split("/"):
            match = re.fullmatch(r"\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*", part)
            if match is None:
                return None
            try:
                value = float(match.group(1))
            except (ValueError, IndexError):
                return None
            if not math.isfinite(value) or value < 0:
                return None
            values.append(value)
        # Same check as the backend's experiment split (and the JS and Java
        # SDKs): the gap from 100 is rounded to two decimals and may be at
        # most 0.01, so "33.33/33.33/33.33" is accepted.
        if not values or round(abs(100 - sum(values)), 2) > 0.01:
            return None
        return RuleAction(split=[value / 100 for value in values])
