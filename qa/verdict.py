"""Application-side verdict. The model reports what it saw; this code decides pass or fail."""

import re

from qa.config import EXPECTED


def to_cents(displayed):
    """'$48.00' -> 4800. Anything unreadable becomes None, never a guess."""
    if displayed is None:
        return None
    match = re.fullmatch(r"\s*\$?\s*(\d+)(?:\.(\d{1,2}))?\s*", str(displayed))
    if not match:
        return None
    return int(match.group(1)) * 100 + int((match.group(2) or "0").ljust(2, "0"))


def judge(record, expected_build):
    """Return pass, fail, or incomplete, plus every check that did not match.

    A record for any build other than expected_build is incomplete: values seen on the
    wrong release say nothing about this one, so they can never make it pass.
    """
    observed = {
        "cart_quantity": record.get("cart_quantity"),
        "cart_subtotal_cents": to_cents(record.get("cart_subtotal")),
        "review_quantity": record.get("review_quantity"),
        "review_subtotal_cents": to_cents(record.get("review_subtotal")),
    }
    missing = [field for field, value in observed.items() if value is None]
    if record.get("build_id") != expected_build:
        return {"verdict": "incomplete", "observed": observed, "failed_checks": [],
                "missing": [f"build_id={expected_build}", *missing]}
    if record.get("stage_reached") != "review":
        missing.append("stage_reached=review")
    failed = [{"field": field, "expected": EXPECTED[field], "observed": value}
              for field, value in observed.items()
              if value is not None and value != EXPECTED[field]]
    verdict = "fail" if failed else "incomplete" if missing else "pass"
    return {"verdict": verdict, "observed": observed, "failed_checks": failed, "missing": missing}


def no_record():
    """Fallback when record_qa_result never arrives: the turn cannot pass."""
    return {"verdict": "incomplete", "observed": {}, "failed_checks": [],
            "missing": ["record_qa_result was never called"]}
