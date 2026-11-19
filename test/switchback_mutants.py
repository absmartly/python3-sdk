"""Mutation probes for switchback serving.

Run with `python -m test.switchback_mutants`. Each mutant is applied to a
temporary copy of the repository (the working tree is never modified) and the
switchback tests must fail against it. Exits non-zero if any mutant survives
or no longer matches the source.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
TESTS = ["test.test_switchback_assigner", "test.test_context_switchback",
         "test.test_context_switchback_cluster"]
CONTEXT = "sdk/context.py"
SERVING = "sdk/internal/switchback_serving.py"
KEYS = "sdk/internal/switchback_cluster_keys.py"
PATH = "sdk/internal/switchback_attribute_path.py"
ASSIGNER = "sdk/internal/switchback_assigner.py"
DRAW = ("        assignment.variant = switchback_assigner.assign(\n"
        "            serving.cluster_key, period,"
        " experiment.switchback.seed,\n"
        "            len(data.split))")
DESIGN = ('        _identity_value(getattr(experiment, '
          '"switchbackDesignType", None)),\n')


def analysis_field(name):
    return (DESIGN, DESIGN + '        _identity_value(getattr(experiment, '
            '"%s", None)),\n' % name)


# Not probed, because they are equivalent: forcing _assignment_at's name
# check to True, and widening _get_assignment_at's check to any routed name.
# Both are reached only for a routed switchback name or after the unit path
# returned None (the name became a switchback), so neither ever sees a unit
# name; the unit fast paths themselves are pinned by
# test_unit_reads_leave_the_switchback_read_time_alone and
# test_unit_candidate_after_a_switchback_skips_switchback_lookup.
MUTANTS = [
    # Cluster order and serving unit.
    ("cluster-order-sorted", SERVING,
     "for unit_type, path in clusters.items():",
     "for unit_type, path in sorted(clusters.items()):"),
    ("cluster-order-reversed", SERVING,
     "for unit_type, path in zip(source_types, source_paths):",
     "for unit_type, path in reversed(list(zip(source_types, "
     "source_paths))):"),
    ("cluster-order-unit-order", SERVING,
     "    for unit_type, path in zip(source_types, source_paths):\n",
     "    for unit_type, path in sorted(zip(source_types, source_paths), "
     "key=lambda e: list(units).index(e[0]) if e[0] in units else 99):\n"),
    ("disagreement-ignored", SERVING,
     "            disagreement = True", "            pass"),
    ("last-value-wins", SERVING,
     "        if key is None:\n            key = value",
     "        if True:\n            key = value"),
    ("allow-list-ignored", SERVING,
     "    if key is None or disagreement or not allowed(allowed_values, key):",
     "    if key is None or disagreement:"),
    ("empty-allow-list-blocks", SERVING,
     "    if not allowed_values:\n        return True",
     "    if allowed_values is None:\n        return True"),
    ("allow-list-str-coerce", SERVING,
     '    return tuple(v for v in values if isinstance(v, str)) or ("",)',
     "    return tuple(str(v) for v in values)"),
    ("ineligible-under-serving-unit", SERVING,
     "        return SwitchbackServing(INELIGIBLE, first, units[first])",
     "        return SwitchbackServing(INELIGIBLE, serving or first, "
     "units[serving or first])"),
    ("legacy-draws", SERVING,
     "        return SwitchbackServing(INELIGIBLE, unit_type, "
     "units[unit_type])",
     "        return SwitchbackServing(ELIGIBLE, unit_type, units[unit_type], "
     "str(units[unit_type]))"),
    # Raw, unhashed cluster key.
    ("hashed-key", CONTEXT, DRAW, DRAW.replace(
        "serving.cluster_key,", "hash_unit(serving.cluster_key),")),
    ("uid-as-key", CONTEXT, DRAW, DRAW.replace(
        "serving.cluster_key,", "str(serving.uid),")),
    ("hashed-uid-as-key", CONTEXT, DRAW, DRAW.replace(
        "serving.cluster_key,", "hash_unit(serving.uid),")),
    ("sticky-unit-draw", CONTEXT, DRAW,
     "        assignment.variant = assigner.assign(data.split, data.seedHi, "
     "data.seedLo)"),
    # Cluster-value rule.
    ("bool-is-int", KEYS,
     "    if isinstance(value, int) and not isinstance(value, bool):",
     "    if isinstance(value, int):"),
    ("whole-float-is-int", KEYS,
     "    if isinstance(value, int) and not isinstance(value, bool):",
     "    if (isinstance(value, int) and not isinstance(value, bool)) or "
     "(isinstance(value, float) and value.is_integer()):"),
    ("float-as-text", KEYS,
     "    if isinstance(value, int) and not isinstance(value, bool):",
     "    if isinstance(value, float):\n        return str(value)\n"
     "    if isinstance(value, int) and not isinstance(value, bool):"),
    ("empty-string-key", KEYS,
     "        return value if len(value) > 0 else None",
     "        return value"),
    ("container-as-key", KEYS,
     "    if isinstance(value, int) and not isinstance(value, bool):",
     "    if isinstance(value, (dict, list)):\n        return str(value)\n"
     "    if isinstance(value, int) and not isinstance(value, bool):"),
    # Period index, schedule and anchor.
    ("period-truncating-division", CONTEXT,
     "        return (now - self.start_at) // self.period_ms",
     "        return int((now - self.start_at) / self.period_ms)"),
    ("period-off-by-one", CONTEXT,
     "        return (now - self.start_at) // self.period_ms",
     "        return (now - self.start_at) // self.period_ms + 1"),
    ("period-ceiling", CONTEXT,
     "        return (now - self.start_at) // self.period_ms",
     "        return -((self.start_at - now) // self.period_ms)"),
    ("pre-anchor-draws", CONTEXT,
     "                not isinstance(now, int) or now < self.start_at:",
     "                not isinstance(now, int):"),
    ("unaligned-anchor-servable", CONTEXT,
     "            self.start_at % _SWITCHBACK_ANCHOR_ALIGNMENT_MS == 0 and \\",
     "            True and \\"),
    ("anchor-upper-bound-dropped", CONTEXT,
     "            0 <= self.start_at < _SWITCHBACK_MAX_ANCHOR_MS and \\",
     "            0 <= self.start_at and \\"),
    ("negative-anchor-servable", CONTEXT,
     "            0 <= self.start_at < _SWITCHBACK_MAX_ANCHOR_MS and \\",
     "            self.start_at < _SWITCHBACK_MAX_ANCHOR_MS and \\"),
    ("one-arm-servable", CONTEXT,
     "isinstance(split, (list, tuple)) and len(split) >= 2",
     "isinstance(split, (list, tuple)) and len(split) >= 1"),
    ("non-positive-period-servable", CONTEXT,
     "self.period_ms is not None and self.period_ms > 0 and \\",
     "self.period_ms is not None and self.period_ms != 0 and \\"),
    ("historic-exposed-at-ignored", CONTEXT,
     "            now = exposed_at if exposed_at is not None else \\\n"
     "                self.clock.millis()\n"
     "            assignment = self._assignment_at(",
     "            now = self.clock.millis()\n"
     "            assignment = self._assignment_at("),
    # Carryover, burn-in and burn-out (and the estimand) are analysis-only:
    # making any of them identity re-exposes on a refresh.
    ("carryover-is-identity", CONTEXT,
     *analysis_field("switchbackCarryoverDurationMs")),
    ("burn-in-is-identity", CONTEXT,
     *analysis_field("switchbackBurnInDurationMs")),
    ("burn-out-is-identity", CONTEXT,
     *analysis_field("switchbackBurnOutDurationMs")),
    ("estimand-is-identity", CONTEXT, *analysis_field("switchbackEstimand")),
    ("design-not-identity", CONTEXT, DESIGN, ""),
    ("clusters-not-identity", CONTEXT,
     '        _identity_value(getattr(experiment, "switchbackClusters", '
     'None)),\n', ""),
    ("allow-list-not-identity", CONTEXT,
     '        _identity_value(getattr(experiment, "switchbackClusterValues", '
     'None)),\n', ""),
    ("cluster-order-not-identity", CONTEXT,
     "            for key, child in reversed(list(item.items())):",
     "            for key, child in reversed(sorted(item.items(), "
     "key=lambda e: repr(e[0]))):"),
    # Holdouts never apply to a switchback.
    ("holdouts-apply", CONTEXT,
     "                switchbacks.append(experiment_variables)\n"
     "            elif holdouts_by_id:",
     "                switchbacks.append(experiment_variables)\n"
     "            if holdouts_by_id:"),
    # Precedence and exposure recording.
    ("pre-anchor-check-after-traffic", CONTEXT,
     "        if period is None:\n            # Before the anchor",
     "        if period is None and False:\n            # Before the anchor"),
    ("custom-before-traffic", CONTEXT,
     "        unit_hash = self.get_unit_hash(unit_type, serving.uid)\n",
     "        if custom is not None:\n           "
     " assignment.variant = custom\n"
     "            assignment.custom = True\n            return\n"
     "        unit_hash = self.get_unit_hash(unit_type, serving.uid)\n"),
    ("traffic-miss-silent", CONTEXT,
     "            # unit experiment.\n           "
     " assignment.eligible = False\n",
     "            # unit experiment.\n           "
     " assignment.eligible = False\n"
     "            assignment.switchback_silent = True\n"),
    ("ineligible-cluster-recorded", CONTEXT,
     "            assignment.eligible = False\n"
     "            assignment.switchback_silent = True\n"
     "            return\n\n        rule_variant",
     "            assignment.eligible = False\n            return\n\n"
     "        rule_variant"),
    ("strict-mismatch-silent", CONTEXT,
     "            # Recorded like a unit experiment's strict mismatch.\n"
     "            assignment.assigned = False\n",
     "            assignment.assigned = False\n"
     "            assignment.switchback_silent = True\n"),
    ("full-on-after-schedule-check", CONTEXT,
     "        if data.fullOnVariant != 0:\n"
     "            assignment.variant = data.fullOnVariant\n",
     "        if period is None:\n            assignment.eligible = False\n"
     "            assignment.switchback_silent = True\n            return\n"
     "        if data.fullOnVariant != 0:\n"
     "            assignment.variant = data.fullOnVariant\n"),
    ("rules-on-ineligible-cluster", CONTEXT,
     "        if serving.status == switchback_serving.INELIGIBLE:\n"
     "            # No value",
     "        if serving.status == switchback_serving.INELIGIBLE and "
     "data.assignmentRules is None:\n            # No value"),
    ("split-rule-on-unit-type", CONTEXT,
     "            data, unit_type=unit_type)\n        assignment.rule_variant",
     "            data)\n        assignment.rule_variant"),
    ("silent-slot-exposes", CONTEXT,
     "        if assignment.switchback_silent:\n",
     "        if assignment.switchback_silent and False:\n"),
    ("exposed-at-enqueue-time", CONTEXT,
     "            assignment, resolved_at if resolved_at is not None\n"
     "            else self.clock.millis())",
     "            assignment, self.clock.millis())"),
    ("override-under-unit-type", CONTEXT,
     "                assignment.unit_type = cached_serving.unit_type or \\\n"
     "                    self._switchback_fallback_unit_type(experiment)",
     "                assignment.unit_type = data.unitType"),
    ("fallback-is-declared-unit-type", CONTEXT,
     "        return sources[0][0] if sources is not None \\\n"
     "            else experiment.data.unitType",
     "        return experiment.data.unitType"),
    # Read once per period slot; retained periods.
    ("serving-reread-per-slot", CONTEXT,
     "            if cached_serving is None or \\\n"
     "                    cached_serving.status == switchback_serving.ABSENT:",
     "            if True:"),
    ("retain-three-periods", CONTEXT,
     "_SWITCHBACK_RETAINED_PERIODS = 2", "_SWITCHBACK_RETAINED_PERIODS = 3"),
    ("evict-newest-period", CONTEXT,
     "            evicted = min(p for p in epoch.periods if p != period)",
     "            evicted = max(p for p in epoch.periods if p != period)"),
    ("epoch-slots-kept", CONTEXT,
     "                self._drop_switchback_epoch(experiment_name)\n"
     "            if switchback is None:",
     "                self._switchback_epochs.pop(experiment_name, None)\n"
     "            if switchback is None:"),
    ("generation-kept-on-identity-change", CONTEXT,
     "                if previous is not None and previous.switchback is not "
     "None \\\n                        and"
     " previous.switchback.identity == \\\n"
     "                        switchback.identity:",
     "                if previous is not None and previous.switchback is not "
     "None:"),
    ("absent-slot-kept-on-set-unit", CONTEXT,
     "                        if not assignment.overridden or \\\n"
     "                                self._retire(assignment):\n"
     "                            del self.assignment_cache[name]",
     "                        pass"),
    ("custom-change-not-stale", CONTEXT,
     "        if not cached.rule_override and cached.switchback_custom != \\\n"
     "                self.custom_assignments.get(experiment_name):\n"
     "            return False", "        pass"),
    ("audience-change-not-stale", CONTEXT,
     "            if mismatch != cached.audience_mismatch:\n"
     "                return False\n",
     "            pass\n"),
    ("attributes-not-revalidated", CONTEXT,
     "        if rule_key == cached.rule_key and \\\n"
     "                self._attrs_seq <= (cached.attrs_seq or 0):",
     "        if rule_key == cached.rule_key:"),
    ("traffic-split-not-checked", CONTEXT,
     "        if data.fullOnVariant != cached.full_on_variant or \\\n"
     "                list(data.trafficSplit or []) != \\\n"
     "                list(cached.traffic_split or []):",
     "        if data.fullOnVariant != cached.full_on_variant:"),
    ("full-on-not-checked", CONTEXT,
     "        if data.fullOnVariant != cached.full_on_variant or \\\n"
     "                list(data.trafficSplit or []) != \\\n"
     "                list(cached.traffic_split or []):",
     "        if list(data.trafficSplit or []) != \\\n"
     "                list(cached.traffic_split or []):"),
    ("randomization-type-case-insensitive", CONTEXT,
     '    return getattr(experiment, "randomizationType", None) == '
     '"switchback"',
     '    return str(getattr(experiment, "randomizationType", None))'
     '.lower() == "switchback"'),
    ("switchback-names-not-pruned", CONTEXT,
     "                self._prune_switchback_names()\n           "
     "     return None",
     "                return None"),
    ("names-without-pending-epochs", CONTEXT,
     "            self._switchback_names = frozenset(\n"
     "                [e.data.name for e in switchbacks] +\n"
     "                list(self._switchback_epochs))",
     "            self._switchback_names = frozenset(\n"
     "                [e.data.name for e in switchbacks])"),
    ("name-not-kept-on-first-epoch", CONTEXT,
     "                self._switchback_names = \\\n"
     "                    self._switchback_names | {experiment_name}",
     "                pass"),
    ("name-kept-only-pre-anchor", CONTEXT,
     "            self._switchback_epochs[experiment_name] = epoch\n"
     "            # A refresh",
     "            self._switchback_epochs[experiment_name] = epoch\n"
     "            if period is not None:\n                return\n"
     "            # A refresh"),
    ("name-update-unlocked", CONTEXT,
     "            try:\n                self.data_lock.acquire_write()\n"
     "                self._switchback_names = \\\n"
     "                    self._switchback_names | {experiment_name}\n"
     "            finally:\n                self.data_lock.release_write()\n"
     "        if period is None:",
     "            self._switchback_names = \\\n"
     "                self._switchback_names | {experiment_name}\n"
     "        if period is None:"),
    ("prune-forgets-pending-epochs", CONTEXT,
     "                 if experiment.switchback is not None] +\n"
     "                list(self._switchback_epochs))\n        finally:",
     "                 if experiment.switchback is not None])\n"
     "        finally:"),
    ("assignment-fields-per-instance", CONTEXT,
     "        self.retired: bool = False\n",
     "        self.retired: bool = False\n"
     "        self.switchback_silent = False\n"),
    ("revalidation-not-recorded", CONTEXT,
     "        cached.rule_key = rule_key\n        cached.attrs_seq = "
     "self._attrs_seq\n        return True",
     "        return True"),
    ("rule-won-audience-rechecked", CONTEXT,
     "        if not cached.rule_override and data.audience is"
     " not None and \\\n"
     "                len(data.audience) > 0:\n            match = self."
     "audience_matcher.evaluate(\n                data.audience, self."
     "_build_audience_attributes())\n            mismatch",
     "        if data.audience is not None and \\\n"
     "                len(data.audience) > 0:\n            match = self."
     "audience_matcher.evaluate(\n                data.audience, self."
     "_build_audience_attributes())\n            mismatch"),
    ("override-value-change-ignored", CONTEXT,
     "            return cached.overridden and \\\n"
     "                cached.variant == self.overrides[experiment_name]",
     "            return cached.overridden"),
    ("silent-slot-skips-close-check", CONTEXT,
     "                self.event_lock.acquire_write()\n"
     "                self.check_not_closed()\n"
     "                if assignment.retired:\n"
     "                    return False\n"
     "                assignment.exposed.compare_and_set(False, True)\n"
     "                return True",
     "                self.event_lock.acquire_write()\n"
     "                if assignment.retired:\n"
     "                    return False\n"
     "                assignment.exposed.compare_and_set(False, True)\n"
     "                return True"),
    ("hook-view-shared", CONTEXT,
     "            view = copy.copy(assignment)\n",
     "            view = assignment\n"),
    ("unit-path-applies-switchback", CONTEXT,
     "            if experiment is not None and experiment.switchback is not "
     "None:\n                return None\n            assignment = "
     "Assignment()",
     "            assignment = Assignment()"),
    ("unit-read-path-applies-switchback", CONTEXT,
     "                if experiment is not None and \\\n"
     "                        experiment.switchback is not None:\n"
     "                    return None\n"
     "                if assignment.data_failed and not failed:",
     "                if assignment.data_failed and not failed:"),
    ("zero-time-is-absent", CONTEXT,
     "            now = exposed_at if exposed_at is not None else \\\n"
     "                self.clock.millis()\n"
     "            assignment = self._assignment_at(",
     "            now = exposed_at if exposed_at else \\\n"
     "                self.clock.millis()\n"
     "            assignment = self._assignment_at("),
    ("resolved-zero-is-absent", CONTEXT,
     "            assignment, resolved_at if resolved_at is not None\n",
     "            assignment, resolved_at if resolved_at\n"),
    ("exposure-not-reconstructible", CONTEXT,
     "        if read_at is None or read_at == now:\n            return now",
     "        if True:\n            return now"),
    ("exposure-always-at-read", CONTEXT,
     "        if (current.status, current.unit_type, current.cluster_key) == "
     "\\\n                (serving.status, serving.unit_type, "
     "serving.cluster_key):\n            return now\n",
     ""),
    ("unbounded-digit-parse", PATH,
     "    if len(significant) > 10:\n        return None\n", ""),
    ("unreadable-switchback-fails-context", CONTEXT,
     "        try:\n            return cls(experiment)\n"
     "        except Exception as e:",
     "        try:\n            return cls(experiment)\n"
     "        except ZeroDivisionError as e:"),
    ("identity-ignores-map-keys", CONTEXT,
     "                stack.append((True, (\"key\", type(key).__name__, "
     "repr(key))))\n", ""),
    ("set-unit-re-exposes-absent-override", CONTEXT,
     "                        if not assignment.overridden or \\\n"
     "                                self._retire(assignment):\n"
     "                            del self.assignment_cache[name]",
     "                        if True:\n"
     "                            del self.assignment_cache[name]"),
    ("absent-serving-not-reread", CONTEXT,
     "            if cached_serving is None or \\\n"
     "                    cached_serving.status == switchback_serving.ABSENT:",
     "            if cached_serving is None:"),
    ("unit-revalidation-applies-switchback", CONTEXT,
     "                    experiment = self.get_experiment(experiment_name)\n"
     "                    if experiment is not None and \\\n"
     "                            experiment.switchback is not None:\n"
     "                        return None\n",
     "                    experiment = self.get_experiment("
     "experiment_name)\n"),
    ("huge-int-raises", KEYS,
     "        try:\n            return str(int(value))\n"
     "        except ValueError:",
     "        try:\n            return str(int(value))\n"
     "        except ZeroDivisionError:"),
    ("variable-walk-clock-for-every-key", CONTEXT,
     "            if name in self._switchback_names:\n"
     "                if now is None:\n"
     "                    now = self.clock.millis()",
     "            if self._switchback_names:\n"
     "                if now is None:\n"
     "                    now = self.clock.millis()"),
    ("walk-handoff-only-when-exposing", CONTEXT,
     "                assignment = self.get_assignment(name) if now is None "
     "\\\n",
     "                assignment = self.get_assignment(name) if now is None "
     "or not expose \\\n"),
    ("treatment-retry-exposes-without-time", CONTEXT,
     "                if assignment.exposed.value or \\\n"
     "                        self._expose_at(assignment, None):\n"
     "                    break\n"
     "        return assignment.variant",
     "                if assignment.exposed.value or \\\n"
     "                        self._expose(assignment):\n"
     "                    break\n"
     "        return assignment.variant"),
    ("walk-unit-branch-rereads-clock", CONTEXT,
     "                    else self._unit_first_at(name, now)",
     "                    else self.get_assignment(name)"),
    ("unit-first-writes-read-time", CONTEXT,
     "    def _unit_first_at(self, experiment_name, now):\n",
     "    def _unit_first_at(self, experiment_name, now):\n"
     "        self._switchback_read.now = None\n"),
    ("unit-first-skipped-after-a-switchback", CONTEXT,
     "        assignment = self._get_unit_assignment(experiment_name, None)\n"
     "        if assignment is not None:\n"
     "            return assignment\n"
     "        return self._assignment_at(experiment_name, None, now)",
     "        return self._assignment_at(experiment_name, None, now)"),
    ("unit-fast-path-for-every-name", CONTEXT,
     "        if experiment_name not in self._switchback_names:\n"
     "            # Unit experiments keep",
     "        if True:\n"
     "            # Unit experiments keep"),
    ("unit-fast-path-removed", CONTEXT,
     "        if experiment_name not in self._switchback_names:\n"
     "            # Unit experiments keep",
     "        if False:\n"
     "            # Unit experiments keep"),
    ("variable-walk-reads-per-experiment", CONTEXT,
     "                if now is None:\n"
     "                    now = self.clock.millis()\n"
     "                assignment = self._assignment_at(name, None, now)",
     "                now = self.clock.millis()\n"
     "                assignment = self._assignment_at(name, None, now)"),
    ("hook-view-loses-retirement", CONTEXT,
     "            view._origin = assignment\n", ""),
    ("variable-fallback-rereads-clock", CONTEXT,
     "        return self._get_assignment_at(experiment_name, exposed_at, "
     "now)",
     "        return self.get_assignment(experiment_name, "
     "exposed_at=exposed_at)"),
    ("expose-at-ignores-handoff-time", CONTEXT,
     "            if resolved_at is None:\n"
     "                resolved_at = getattr(self._switchback_read, \"now\", "
     "None)\n",
     ""),
    ("attribute-first-wins", CONTEXT,
     "                    (selected is None or set_at >= selected.setAt):",
     "                    (selected is None):"),
    ("future-attribute-visible", CONTEXT,
     "isinstance(set_at, (int, float)) and set_at <= now and \\",
     "isinstance(set_at, (int, float)) and \\"),
    ("attribute-name-python-strip", CONTEXT,
     "                    attribute.name.strip(_JAVA_TRIM) == name and \\",
     "                    attribute.name.strip() == name and \\"),
    ("attribute-name-not-trimmed", CONTEXT,
     "                    attribute.name.strip(_JAVA_TRIM) == name and \\",
     "                    attribute.name == name and \\"),
    # Attribute paths.
    ("dotted-path-readable", PATH,
     '    if "." in path:\n        return None', "    pass"),
    ("unterminated-quote-readable", PATH,
     "            if end < 0:\n                return None",
     "            if end < 0:\n                end = length"),
    ("trailing-index-supported", PATH,
     "(index < 0 or i == 0 or i == n - 1 or",
     "(index < 0 or i == 0 or"),
    ("plus-sign-index", PATH,
     '    negative = s.startswith("-")',
     '    s = s.lstrip("+")\n    negative = s.startswith("-")'),
    # 64-bit seed and the assigner.
    ("seed-low-word-sign-extended", CONTEXT,
     "        self.seed = (seed_hi << 32) | (seed_lo & 0xffffffff)",
     "        self.seed = (seed_hi << 32) | seed_lo"),
    ("seed-words-swapped", CONTEXT,
     "        self.seed = (seed_hi << 32) | (seed_lo & 0xffffffff)",
     "        self.seed = (seed_lo << 32) | (seed_hi & 0xffffffff)"),
    ("assigner-separator", ASSIGNER,
     '_SEPARATOR = "\\u001f"', '_SEPARATOR = ":"'),
    ("assigner-truncating-cycle", ASSIGNER,
     "    cycle_index = period_index // arm_count\n"
     "    cycle_slot = period_index % arm_count",
     "    cycle_index = int(period_index / arm_count)\n"
     "    cycle_slot = period_index - cycle_index * arm_count"),
    ("assigner-seed-high-word-first", ASSIGNER,
     "    buffers.put_uint32(buffer, 0, seed & 0xffffffff)\n"
     "    buffers.put_uint32(buffer, 4, (seed >> 32) & 0xffffffff)",
     "    buffers.put_uint32(buffer, 4, seed & 0xffffffff)\n"
     "    buffers.put_uint32(buffer, 0, (seed >> 32) & 0xffffffff)"),
    ("assigner-step-unclamped", ASSIGNER,
     "        j = min(i, math.floor(prob * (i + 1)))",
     "        j = math.floor(prob * i)"),
    ("assigner-lone-surrogate-replaced", ASSIGNER,
     '            .encode("utf-8", "surrogatepass")',
     '            .encode("utf-8", "replace")'),
]


def main(selected):
    unknown = selected - {name for name, _, _, _ in MUTANTS}
    if unknown:
        print(f"unknown mutants: {sorted(unknown)}")
        return 2
    failures = []
    executed = 0
    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / "repo"
        shutil.copytree(REPO, work, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "venv*", ".venv", "build", "dist"))
        for name, rel, old, new in MUTANTS:
            if selected and name not in selected:
                continue
            path = work / rel
            source = path.read_text()
            if source.count(old) != 1:
                print(f"{name}: pattern found {source.count(old)} times")
                failures.append(name)
                continue
            mutated = source.replace(old, new)
            try:
                compile(mutated, str(path), "exec")
            except SyntaxError as e:
                print(f"{name}: INVALID ({e})", flush=True)
                failures.append(name + " (invalid)")
                continue
            path.write_text(mutated)
            executed += 1
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", *TESTS], cwd=work,
                    capture_output=True, text=True, timeout=600)
                killed = result.returncode != 0
            except subprocess.TimeoutExpired:
                killed = True
            finally:
                path.write_text(source)
            print(f"{name}: {'killed' if killed else 'SURVIVED'}", flush=True)
            if not killed:
                failures.append(name)
    print(f"{executed} of {len(MUTANTS)} mutants run, failures: "
          f"{failures or 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(set(sys.argv[1:])))
