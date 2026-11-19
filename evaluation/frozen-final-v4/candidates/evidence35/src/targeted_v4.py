"""Apply the individually verified checks to the same original v4 findings."""

from .event_approval import CATEGORY as EVENT, with_event_approval
from .stall_operating_days import CATEGORY as OCCUPANCY, with_operating_days
from .stall_repair_closure import with_repair_closure
from .traffic_loading import CATEGORY as TRAFFIC, with_traffic_loading
from .vendor_id_display import with_vendor_id_display
from .vendor_id_stall import CATEGORY as VENDOR_ID, with_vendor_id_stall


CHECKS = {
    "event-approval": (EVENT, with_event_approval),
    "vendor-id-stall": (VENDOR_ID, with_vendor_id_stall),
    "vendor-id-display": (VENDOR_ID, with_vendor_id_display),
    "stall-operating-days": (OCCUPANCY, with_operating_days),
    "stall-repair-closure": (OCCUPANCY, with_repair_closure),
    "traffic-loading": (TRAFFIC, with_traffic_loading),
}


def with_targeted_v4(description, baseline_codes, normalize):
    """Apply the scoped additions and event veto, with per-check evidence."""
    baseline = frozenset(baseline_codes)
    findings = set(baseline)
    checks = {}
    for name, (category, apply) in CHECKS.items():
        proposed, evidence = apply(description, baseline, normalize)
        added, removed = proposed - baseline, baseline - proposed
        if (added | removed) - {category} or (removed and name != "event-approval"):
            raise ValueError(f"Check changed a finding outside its scope: {name}")
        findings.update(added)
        findings.difference_update(removed)
        if evidence or added or removed:
            checks[name] = (evidence, sorted(added), sorted(removed))
    return findings, checks
