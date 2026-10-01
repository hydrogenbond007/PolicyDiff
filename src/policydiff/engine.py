"""Behavioral changes, missingness and deliberately bounded inference."""
from __future__ import annotations

from copy import deepcopy
from ._version import __version__
from .schema import OUTCOMES, STATUSES, revisions, validate_manifest, validate_rows
from .statistics import harmful_flip_upper_bound, regression_p


def _counts(pairs):
    return {"pairs": len(pairs),
            "baseline_successes": sum(b["success"] for b, _ in pairs),
            "candidate_successes": sum(c["success"] for _, c in pairs),
            "harmful_flips": sum(b["success"] and not c["success"] for b, c in pairs),
            "helpful_flips": sum(c["success"] and not b["success"] for b, c in pairs)}


def _metric(pairs, field):
    available = [(b[field], c[field]) for b, c in pairs if b[field] is not None and c[field] is not None]
    return {"paired_values": len(available), "paired_outcomes": len(pairs),
            "baseline_mean": sum(b for b, _ in available) / len(available) if available else None,
            "candidate_mean": sum(c for _, c in available) / len(available) if available else None,
            "mean_change": sum(c - b for b, c in available) / len(available) if available else None,
            "scope": "Observed paired values only; stopping/failure censoring and missing metrics can bias means."}


def compare(manifest, rows):
    """Validate and compare one revision pair; inputs are not modified.

    Metadata are caller attestations. This API does not run policies, inspect
    weights or certify training exposure, sampling independence or deployment.
    """
    validate_manifest(manifest)
    table = validate_rows(manifest, rows)
    base_id, candidate_id = manifest["baseline"]["id"], manifest["candidate"]["id"]
    retest_id = manifest.get("retest", {}).get("id")
    policy_ids = [r["id"] for r in revisions(manifest)]
    family_size = len(manifest["slices"])
    alpha = manifest["sampling"]["alpha"] / family_size
    slices = []
    for sl in manifest["slices"]:
        present = {rid: [table[rid, sl["id"], case] for case in sl["case_ids"]
                         if (rid, sl["id"], case) in table] for rid in policy_ids}
        missing = {rid: [case for case in sl["case_ids"] if (rid, sl["id"], case) not in table]
                   for rid in policy_ids}
        summaries = {}
        for rid, records in present.items():
            outcomes = [r for r in records if r["status"] in OUTCOMES]
            summaries[rid] = {"expected": len(sl["case_ids"]), "records": len(records),
                              "scored_outcomes": len(outcomes), "successes": sum(r["success"] for r in outcomes),
                              "terminal_status_counts": {status: sum(r['status'] == status for r in records) for status in STATUSES},
                              "missing_cases": missing[rid]}
        pairs, retest_pairs, cases = [], [], []
        partition = {"both_outcomes": 0, "baseline_only_outcome": 0,
                     "candidate_only_outcome": 0, "neither_outcome": 0}
        for case in sl["case_ids"]:
            records = {rid: table.get((rid, sl["id"], case)) for rid in policy_ids}
            b, c = records[base_id], records[candidate_id]
            b_ok = b is not None and b["status"] in OUTCOMES
            c_ok = c is not None and c["status"] in OUTCOMES
            transition = "unresolved"
            if b_ok and c_ok:
                pairs.append((b, c))
                partition["both_outcomes"] += 1
                transition = ("lost" if b["success"] and not c["success"] else
                              "gained" if not b["success"] and c["success"] else
                              "retained_success" if b["success"] else "shared_failure")
            elif b_ok:
                partition["baseline_only_outcome"] += 1
            elif c_ok:
                partition["candidate_only_outcome"] += 1
            else:
                partition["neither_outcome"] += 1
            r = records.get(retest_id)
            if b_ok and r is not None and r["status"] in OUTCOMES:
                retest_pairs.append((b, r))
            cases.append({"id": case, "transition": transition,
                          "records": {rid: ({k: record[k] for k in ("status", "success", "steps", "wall_seconds", "evidence_ref")}
                                            if record is not None else None) for rid, record in records.items()}})

        counts = _counts(pairs)
        counts["declared_pairs"] = len(sl["case_ids"])
        counts["discordant_pairs"] = counts["harmful_flips"] + counts["helpful_flips"]
        counts["net_success_change"] = (counts["candidate_successes"] - counts["baseline_successes"]) / len(pairs) if pairs else None
        coverage = ("not_tested" if not any(present.values()) else "complete"
                    if all(summaries[rid]["scored_outcomes"] == len(sl["case_ids"]) for rid in policy_ids)
                    else "incomplete")
        reasons = []
        if manifest["evidence_origin"] == "synthetic":
            reasons.append("synthetic fixtures are not population evidence")
        if manifest["sampling"]["design"] != "iid_pairs":
            reasons.append("IID paired sampling was not attested")
        if not manifest["sampling"]["frozen_before_outcomes"]:
            reasons.append("comparison was not declared frozen before outcomes")
        if coverage != "complete":
            reasons.append("incomplete or untested declared comparison population")
        if not retest_id or len(retest_pairs) != len(sl["case_ids"]):
            reasons.append("complete unchanged-policy retest is absent")
        if not sl["role"].startswith("old_"):
            reasons.append("formal retention inference is restricted to old-task slices")
        baseline = summaries[base_id]
        if baseline["successes"] == 0:
            reasons.append("no measured baseline successes to retain")
        elif (baseline["scored_outcomes"] == len(sl["case_ids"])
              and baseline["successes"] / len(sl["case_ids"]) < manifest["sampling"]["minimum_baseline_success_rate"]):
            reasons.append("baseline is below the caller-declared competence threshold")
        eligible = not reasons
        retest_counts = _counts(retest_pairs) if retest_id else None
        retest = ({"arm": retest_id, "pairs": len(retest_pairs), "declared_pairs": len(sl["case_ids"]),
                   "coverage": 'not_tested' if not present[retest_id] else 'complete'
                   if len(retest_pairs) == len(sl['case_ids']) else 'incomplete',
                   "baseline_successes": retest_counts["baseline_successes"],
                   "retest_successes": retest_counts["candidate_successes"],
                   "churn_losses": retest_counts["harmful_flips"], "churn_gains": retest_counts["helpful_flips"],
                   "discordant_pairs": retest_counts["harmful_flips"] + retest_counts["helpful_flips"]}
                  if retest_id else None)
        infer = {"eligible": eligible, "ineligible_reasons": reasons,
                 "status": "descriptive_only", "per_slice_alpha": alpha,
                 "regression_p": None, "harmful_flip_probability_upper_bound": None,
                 "unchanged_retest_discordant_pairs": retest["discordant_pairs"] if retest and retest['coverage'] == 'complete' else None,
                 "churn_caveat": "Retest churn is not subtracted; observed candidate changes may not be attributable to the update."}
        if eligible:
            p = regression_p(counts["harmful_flips"], counts["helpful_flips"])
            upper = harmful_flip_upper_bound(counts["harmful_flips"], len(pairs), alpha)
            infer.update(regression_p=p, harmful_flip_probability_upper_bound=upper,
                         status="regression_detected" if p <= alpha else "within_declared_harm_bound"
                         if upper <= manifest["sampling"]["maximum_harm_probability"] else "inconclusive")
        exposure = "not_a_held_out_test"
        if sl["role"] == "held_out":
            exposure = "excluded_from_declared_parent_and_update" if sl["parent_exposure"] == "excluded" else "parent_exposure_unknown"
        slices.append({"id": sl["id"], "task": sl["task"], "role": sl["role"],
                       "condition": sl["condition"], "axis": sl["axis"], "required": sl["required"],
                       "coverage": coverage, "revisions": summaries, "observed_pairs": counts,
                       "outcome_coverage": partition,
                       "unchanged_retest": retest,
                       "inference": infer, "exposure_status": exposure,
                       "metrics": {key: _metric(pairs, key) for key in ("steps", "wall_seconds")},
                       "cases": cases})
    eligible_count = sum(s["inference"]["eligible"] for s in slices)
    observed_totals = {"lost": sum(s["observed_pairs"]["harmful_flips"] for s in slices),
                       "gained": sum(s["observed_pairs"]["helpful_flips"] for s in slices),
                       "unresolved": sum(s["observed_pairs"]["declared_pairs"] - s["observed_pairs"]["pairs"] for s in slices),
                       "declared_pairs": sum(s["observed_pairs"]["declared_pairs"] for s in slices),
                       "paired_outcomes": sum(s["observed_pairs"]["pairs"] for s in slices),
                       "scope": "Descriptive slice-case counts, not independent pooled trials or a release score."}
    return {"report_schema_version": 1, "input_schema_version": manifest['schema_version'],
            "producer": {"name": "policydiff", "version": __version__}, "inputs": None,
            "status": "report_created", "input_valid": True,
            "evidence_origin": manifest["evidence_origin"], "title": manifest["title"],
            "baseline": base_id, "candidate": candidate_id, "retest": retest_id,
            "change_kind": manifest["change"]["kind"],
            "upstream_exposure": manifest["change"]["upstream_exposure"],
            "required_coverage_complete": all(s["coverage"] == "complete" for s in slices if s["required"]),
            "coverage_counts": {coverage: sum(s['coverage'] == coverage for s in slices)
                                for coverage in ('complete', 'incomplete', 'not_tested')},
            "family_alpha": manifest["sampling"]["alpha"], "declared_family_size": family_size,
            "eligible_slice_count": eligible_count, "observed_totals": observed_totals,
            "has_inferential_regression": any(s["inference"]["status"] == "regression_detected" for s in slices) if eligible_count else None,
            "slices": slices, "manifest": deepcopy(manifest),
            "limitations": [
                "This is an evidence report, not a safety certificate or permission to deploy.",
                "Caller-supplied hashes/exposure labels do not prove physical execution, training history or IID sampling.",
                "Paired flips can reflect stochastic variability; retest churn is descriptive and is not subtracted as a causal correction.",
                "Inference covers this fixed, declared slice family only; not repeated releases, adaptive selection or sequential peeking.",
                "Alpha correction is separate for regression tests and harmful-flip bounds, not a joint guarantee across both endpoint families.",
                "Incomplete-pair summaries describe observed subsets; they do not estimate the full declared population.",
                "Held-out status is relative to declared data; unknown upstream pretraining is not proof of novelty.",
                "No inference about untested objects, tasks, embodiments or sim-to-real transfer follows.",
                "Evidence references are unverified local references; this package never opens or executes them.",
                "The v1 endpoint is the supplied Boolean task outcome under each slice contract; no stable-success inference from truncated traces."]}
