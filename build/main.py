#!/usr/bin/env python3
"""
Corrigan Peak Logistics - Dispatch Exception Triage
FreightWorks EDI exception export normalizer.

Takes the raw exception export, normalizes terminal / carrier code /
timestamp into consistent values, and produces a summary count by event
type plus an explicit review queue for records that could not be cleaned
with confidence.

Design rule: nothing is dropped and nothing is silently guessed. Every
record in the input appears in the output. Where a value could not be
determined, it is flagged with the reason rather than filled in.

Python 3.12+. Standard library only. No credentials, no network.

    python main.py                  normalize the bundled export
    python main.py --selftest       run the verification suite
    python main.py --in FILE.csv    normalize a different export
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# "Terminal 3", "T3", "terminal3", "T-3" all mean the same terminal.
TERMINAL_RE = re.compile(r"^(?:terminal|term|t)\s*[-_]?\s*(\d+)$", re.IGNORECASE)

# Carrier codes in this feed are short alphanumeric SCAC-style codes.
CARRIER_RE = re.compile(r"^[A-Z0-9]{2,6}$")

# 08/14/2026 09:45  /  08/15/2026 08:02:11
SLASH_TS_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?$"
)

OUTPUT_COLUMNS = [
    "exception_id",
    "terminal",
    "event_type",
    "carrier_code",
    "event_ts",
    "ts_basis",
    "scoring_ready",
    "needs_review",
    "review_reason",
]


@dataclass
class Row:
    """One normalized exception record."""

    exception_id: str
    terminal: str | None
    event_type: str | None
    carrier_code: str | None
    event_ts: str | None
    ts_basis: str | None
    reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        """
        True when THIS record has a defect I could not resolve.
        Record-level. Answers: is this row clean?
        """
        return bool(self.reasons)

    @property
    def scoring_ready(self) -> bool:
        """
        True only when the timestamp carried an explicit timezone.

        Separate from needs_review on purpose. A record can be perfectly
        clean - consistent formatting, nothing guessed - and still be unsafe
        to feed the urgency scorer, because the scorer does elapsed-time
        arithmetic and an unknown timezone basis silently shifts the answer.
        "Clean" and "trustworthy for scoring" are two different questions and
        they need two different columns.
        """
        return self.ts_basis == "explicit_utc"

    def as_output(self) -> dict:
        return {
            "exception_id": self.exception_id,
            "terminal": self.terminal or "",
            "event_type": self.event_type or "",
            "carrier_code": self.carrier_code or "",
            "event_ts": self.event_ts or "",
            "ts_basis": self.ts_basis or "",
            "scoring_ready": "yes" if self.scoring_ready else "no",
            "needs_review": "yes" if self.needs_review else "no",
            "review_reason": "; ".join(self.reasons),
        }


# --------------------------------------------------------------------------
# Field normalizers. Each returns (value, reason_or_None).
# A reason means "I could not do this confidently" - it never means "dropped".
# --------------------------------------------------------------------------


def normalize_terminal(raw: str | None) -> tuple[str | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, "terminal is empty in the source record"
    match = TERMINAL_RE.match(value)
    if match:
        return f"Terminal {int(match.group(1))}", None
    return value, f"terminal {value!r} does not match a known naming pattern"


def normalize_carrier(raw: str | None) -> tuple[str | None, str | None]:
    value = (raw or "").strip().upper()
    if not value:
        # Deliberately not inferred. A carrier code drives who gets billed and
        # who gets called; guessing one is worse than leaving it blank.
        return None, "carrier_code is missing in the source and cannot be inferred"
    if not CARRIER_RE.match(value):
        return value, f"carrier_code {value!r} has an unexpected shape"
    return value, None


def normalize_timestamp(
    raw: str | None,
) -> tuple[str | None, str | None, str | None]:
    """
    Returns (iso_timestamp, basis, reason).

    basis is 'explicit_utc' when the source carried a timezone, and
    'unspecified' when it did not. That distinction is preserved rather than
    flattened, because the urgency score is a function of elapsed time and a
    wrong timezone silently produces a wrong score.
    """
    value = (raw or "").strip()
    if not value:
        return None, None, "event_ts is empty in the source record"

    # Explicit UTC: 2026-08-14T10:03:00Z
    if value.endswith("Z"):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%MZ"):
            try:
                dt = datetime.strptime(value, fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z", "explicit_utc", None
            except ValueError:
                continue

    # ISO-ish without a zone: 2026-08-14 09:12:00
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S"), "unspecified", None
        except ValueError:
            continue

    # US-style slash format: 08/14/2026 09:45
    match = SLASH_TS_RE.match(value)
    if match:
        first, second, year, hour, minute, sec = match.groups()
        first_i, second_i = int(first), int(second)
        reason = None

        if first_i > 12 and second_i <= 12:
            # Only DD/MM can be true here.
            month, day = second_i, first_i
            reason = f"timestamp {value!r} read as DD/MM/YYYY; MM/DD is impossible"
        elif first_i <= 12 and second_i <= 12:
            # Genuinely ambiguous - both readings are valid dates.
            month, day = first_i, second_i
            reason = (
                f"timestamp {value!r} is ambiguous (MM/DD vs DD/MM); "
                "read as MM/DD/YYYY, needs confirmation from Corrigan Peak IT"
            )
        else:
            month, day = first_i, second_i

        try:
            dt = datetime(int(year), month, day, int(hour), int(minute), int(sec or 0))
        except ValueError:
            return value, None, f"timestamp {value!r} is not a valid date"
        return dt.strftime("%Y-%m-%dT%H:%M:%S"), "unspecified", reason

    return value, None, f"timestamp {value!r} is in an unrecognized format"


def normalize_event_type(raw: str | None) -> tuple[str | None, str | None]:
    value = (raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not value:
        return None, "event_type is empty in the source record"
    return value, None


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


def normalize_rows(raw_rows: list[dict]) -> list[Row]:
    out: list[Row] = []
    for raw in raw_rows:
        reasons: list[str] = []

        terminal, r = normalize_terminal(raw.get("terminal"))
        if r:
            reasons.append(r)

        event_type, r = normalize_event_type(raw.get("event_type"))
        if r:
            reasons.append(r)

        carrier, r = normalize_carrier(raw.get("carrier_code"))
        if r:
            reasons.append(r)

        ts, basis, r = normalize_timestamp(raw.get("event_ts"))
        if r:
            reasons.append(r)

        out.append(
            Row(
                exception_id=(raw.get("exception_id") or "").strip(),
                terminal=terminal,
                event_type=event_type,
                carrier_code=carrier,
                event_ts=ts,
                ts_basis=basis,
                reasons=reasons,
            )
        )

    # Guard against silent data loss - the most dangerous failure in a
    # pipeline like this is a row that quietly disappears.
    assert len(out) == len(raw_rows), "row count changed during normalization"
    return out


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]


def write_csv(rows: list[Row], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_output())


def render_report(rows: list[Row]) -> str:
    lines: list[str] = []
    counts = Counter(r.event_type or "(missing)" for r in rows)

    lines.append("EXCEPTION SUMMARY BY EVENT TYPE")
    lines.append("-" * 52)
    width = max((len(k) for k in counts), default=10)
    for event_type, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"  {event_type:<{width}}  {count:>3}")
    lines.append("-" * 52)
    lines.append(f"  {'total':<{width}}  {len(rows):>3}")
    lines.append("")

    flagged = [r for r in rows if r.needs_review]
    lines.append(f"RECORDS I COULD NOT CLEAN WITH CONFIDENCE: {len(flagged)}")
    lines.append("-" * 52)
    if not flagged:
        lines.append("  none")
    for row in flagged:
        lines.append(f"  {row.exception_id}")
        for reason in row.reasons:
            lines.append(f"      - {reason}")
    lines.append("")

    not_ready = [r for r in rows if not r.scoring_ready]
    ready = [r for r in rows if r.scoring_ready]
    lines.append(f"NOT SAFE TO SCORE YET: {len(not_ready)} of {len(rows)}")
    lines.append("-" * 52)
    lines.append("  Clean is not the same thing as trustworthy. These records")
    lines.append("  normalized without any guessing, but carry no timezone:")
    for row in not_ready:
        lines.append(f"      {row.exception_id}  {row.event_ts}  (basis unknown)")
    lines.append(
        f"  {len(ready)} record(s) carry an explicit UTC offset and can be scored."
    )
    lines.append("")

    lines.append("OPEN QUESTION FOR CORRIGAN PEAK IT")
    lines.append("-" * 52)
    lines.append("  Are the un-zoned timestamps terminal-local or UTC?")
    lines.append("")
    lines.append("  This is tracked in its own column rather than as a per-record")
    lines.append("  defect, because it is ONE question about the feed, not four")
    lines.append("  separate record problems. Flagging 4 of 5 rows for review")
    lines.append("  would leave a queue nobody triages - the same failure mode as")
    lines.append("  the shared inbox this tool exists to replace.")
    lines.append("")
    lines.append("  It matters because urgency scoring is elapsed-time arithmetic.")
    lines.append("  The wrong basis produces confidently wrong scores with no")
    lines.append("  error to notice - the same shape as the null scores in")
    lines.append("  DET-121. Confirm before this feed drives live routing.")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Verification. Checks that it produced the RIGHT answer, not that it ran.
# Expected values below were worked out by hand from the export first.
# --------------------------------------------------------------------------


def selftest() -> int:
    failures: list[str] = []

    def check(label: str, got, want):
        if got != want:
            failures.append(f"{label}\n      expected: {want!r}\n      got:      {got!r}")

    # Field-level, including the cases the sample data does not contain.
    check("T3 -> Terminal 3", normalize_terminal("T3")[0], "Terminal 3")
    check("Terminal 3 unchanged", normalize_terminal("Terminal 3")[0], "Terminal 3")
    check("lowercase carrier", normalize_carrier("swft")[0], "SWFT")
    check("mixed-case carrier", normalize_carrier("Swft")[0], "SWFT")
    check("empty carrier is None", normalize_carrier("")[0], None)
    check(
        "empty carrier is flagged",
        normalize_carrier("")[1] is not None,
        True,
    )

    check(
        "naive ts",
        normalize_timestamp("2026-08-14 09:12:00")[:2],
        ("2026-08-14T09:12:00", "unspecified"),
    )
    check(
        "utc ts keeps its Z",
        normalize_timestamp("2026-08-14T10:03:00Z")[:2],
        ("2026-08-14T10:03:00Z", "explicit_utc"),
    )
    check(
        "slash ts",
        normalize_timestamp("08/14/2026 09:45")[:2],
        ("2026-08-14T09:45:00", "unspecified"),
    )
    # 14 > 12, so MM/DD is impossible and no ambiguity warning should fire.
    check(
        "unambiguous slash date is not flagged",
        normalize_timestamp("08/14/2026 09:45")[2],
        None,
    )
    # Both readings valid -> must warn rather than silently pick one.
    check(
        "ambiguous slash date IS flagged",
        normalize_timestamp("08/09/2026 09:45")[2] is not None,
        True,
    )
    # Impossible as MM/DD, so it must be read as DD/MM.
    check(
        "day-first date is detected",
        normalize_timestamp("14/08/2026 09:45")[0],
        "2026-08-14T09:45:00",
    )
    check(
        "garbage ts is flagged, not crashed",
        normalize_timestamp("not a date")[2] is not None,
        True,
    )

    # End-to-end against the bundled export.
    rows = normalize_rows(read_csv(Path(__file__).parent / "exceptions_raw.csv"))

    check("no rows lost", len(rows), 5)
    check(
        "all terminals collapse to one value",
        {r.terminal for r in rows},
        {"Terminal 3"},
    )
    check(
        "carrier codes normalized",
        [r.carrier_code for r in rows],
        ["SWFT", "SWFT", "SWFT", None, "RLCX"],
    )
    check(
        "counts by event type",
        dict(Counter(r.event_type for r in rows)),
        {"missed_pickup": 2, "doc_mismatch": 2, "carrier_substitution": 1},
    )
    check(
        "exactly one record needs review",
        [r.exception_id for r in rows if r.needs_review],
        ["CPX-88216"],
    )
    check(
        "every timestamp parsed",
        all(r.event_ts for r in rows),
        True,
    )
    check(
        "timezone basis preserved, not flattened",
        Counter(r.ts_basis for r in rows),
        Counter({"unspecified": 4, "explicit_utc": 1}),
    )
    # "Clean" and "safe to score" must not collapse into one another.
    check(
        "only the explicitly-zoned record is scoring_ready",
        [r.exception_id for r in rows if r.scoring_ready],
        ["CPX-88215"],
    )
    check(
        "a record can be clean but NOT scoring_ready",
        [r.exception_id for r in rows if not r.needs_review and not r.scoring_ready],
        ["CPX-88213", "CPX-88214", "CPX-88217"],
    )

    if failures:
        print(f"SELFTEST FAILED - {len(failures)} check(s)\n")
        for f in failures:
            print(f"  [FAIL] {f}\n")
        return 1

    print("SELFTEST PASSED - 21 checks")
    print("Checked against hand-computed expected values, not just exit status.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).parent
    parser.add_argument("--in", dest="infile", type=Path, default=here / "exceptions_raw.csv")
    parser.add_argument("--out", dest="outfile", type=Path, default=here / "exceptions_clean.csv")
    parser.add_argument("--selftest", action="store_true", help="run verification suite")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if not args.infile.exists():
        print(f"input not found: {args.infile}", file=sys.stderr)
        return 2

    raw = read_csv(args.infile)
    rows = normalize_rows(raw)
    write_csv(rows, args.outfile)

    print(f"read  {len(raw)} records from {args.infile.name}")
    print(f"wrote {len(rows)} records to   {args.outfile.name}")
    print()
    print(render_report(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
