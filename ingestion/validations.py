"""Row-level validation contracts per source. Bad rows are quarantined, never loaded to raw."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

UTC = timezone.utc
FUTURE_TOLERANCE = timedelta(minutes=10)


class Reject(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


@dataclass(frozen=True)
class Contract:
    key: str
    required: tuple[str, ...]
    timestamps: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    enums: dict[str, frozenset] = field(default_factory=dict)
    booleans: tuple[str, ...] = ()
    integers: tuple[str, ...] = ()
    decimals: tuple[str, ...] = ()
    # (earlier, later): later must be >= earlier when both are present
    ordering: tuple[tuple[str, str], ...] = ()


TICKET_STATUSES = frozenset({"new", "open", "pending", "on_hold", "resolved", "closed"})

CONTRACTS: dict[str, Contract] = {
    "tickets": Contract(
        key="ticket_id",
        required=("ticket_id", "customer_id", "priority", "status", "created_at", "updated_at"),
        timestamps=("created_at", "first_response_at", "resolved_at", "closed_at",
                    "reopened_at", "updated_at"),
        enums={"status": TICKET_STATUSES,
               "priority": frozenset({"urgent", "high", "medium", "low"}),
               "channel": frozenset({"email", "chat", "phone", "web_form", "social"})},
        integers=("reopen_count",),
        ordering=(("created_at", "first_response_at"), ("created_at", "resolved_at"),
                  ("resolved_at", "closed_at"), ("created_at", "reopened_at"),
                  ("created_at", "updated_at")),
    ),
    "agents": Contract(
        key="agent_id",
        required=("agent_id", "agent_name", "updated_at"),
        timestamps=("updated_at",),
        dates=("hire_date", "termination_date"),
        enums={"team": frozenset({"tier_1", "tier_2", "technical", "billing"}),
               "shift": frozenset({"day", "evening", "night"})},
        booleans=("is_active",),
        ordering=(("hire_date", "termination_date"),),
    ),
    "sales_orders": Contract(
        key="order_id",
        required=("order_id", "customer_id", "order_date", "amount", "updated_at"),
        timestamps=("updated_at",),
        dates=("order_date",),
        enums={"status": frozenset({"paid", "failed", "refunded", "pending"}),
               "order_type": frozenset({"new", "renewal", "upgrade", "downgrade"}),
               "billing_cycle": frozenset({"monthly", "annual"})},
        decimals=("amount",),
    ),
    "csat_surveys": Contract(
        key="survey_id",
        required=("survey_id", "ticket_id", "sent_at", "updated_at"),
        timestamps=("sent_at", "responded_at", "updated_at"),
        integers=("score",),
        ordering=(("sent_at", "responded_at"),),
    ),
    "crm_customers": Contract(
        key="customer_id",
        required=("customer_id", "company_name", "updated_at"),
        timestamps=("updated_at",),
        dates=("signup_date", "churn_date"),
        enums={"segment": frozenset({"smb", "mid-market", "enterprise"}),
               "billing_cycle": frozenset({"monthly", "annual"})},
        booleans=("is_active",),
        ordering=(("signup_date", "churn_date"),),
    ),
}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def parse_ts(value: str) -> datetime:
    """ISO-8601; naive values are UTC by source contract (billing + survey exports)."""
    ts = datetime.fromisoformat(value.strip())
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)


def validate_row(source: str, row: dict, now: datetime) -> dict:
    """Return a typed copy of `row` or raise Reject(reason)."""
    c = CONTRACTS[source]
    out = {k: (None if _blank(v) else (v.strip() if isinstance(v, str) else v)) for k, v in row.items()}
    for f in c.required:
        if out.get(f) is None:
            raise Reject("null_required_field", f)
    for f in c.timestamps:
        if out.get(f) is not None:
            try:
                out[f] = parse_ts(str(out[f]))
            except ValueError:
                raise Reject("invalid_timestamp", f"{f}={row.get(f)!r}")
            if out[f] > now + FUTURE_TOLERANCE:
                raise Reject("future_timestamp", f"{f}={row.get(f)!r}")
    for f in c.dates:
        if out.get(f) is not None:
            try:
                out[f] = date.fromisoformat(str(out[f])[:10])
            except ValueError:
                raise Reject("invalid_date", f"{f}={row.get(f)!r}")
    for f, allowed in c.enums.items():
        v = out.get(f)
        if v is not None and str(v).strip().lower() not in allowed:
            raise Reject(f"invalid_{f}", f"{f}={row.get(f)!r}")
    for f in c.booleans:
        v = out.get(f)
        if v is not None and not isinstance(v, bool):
            s = str(v).lower()
            if s not in ("true", "false", "1", "0"):
                raise Reject("invalid_boolean", f"{f}={v!r}")
            out[f] = s in ("true", "1")
    for f in c.integers:
        if out.get(f) is not None:
            try:
                out[f] = int(str(out[f]))
            except ValueError:
                raise Reject("invalid_integer", f"{f}={row.get(f)!r}")
    for f in c.decimals:
        if out.get(f) is not None:
            try:
                out[f] = Decimal(str(out[f]))
            except InvalidOperation:
                raise Reject("invalid_decimal", f"{f}={row.get(f)!r}")
    for earlier, later in c.ordering:
        a, b = out.get(earlier), out.get(later)
        if a is not None and b is not None and b < a:
            raise Reject("invalid_timestamp_order", f"{later} < {earlier}")
    _business_rules(source, out)
    return out


def _business_rules(source: str, r: dict) -> None:
    if source == "tickets":
        status = r["status"].lower()
        if status in ("resolved", "closed") and r.get("resolved_at") is None:
            raise Reject("status_inconsistent", f"status={r['status']} without resolved_at")
        if status not in ("resolved", "closed") and r.get("resolved_at") is not None:
            raise Reject("status_inconsistent", f"status={r['status']} with resolved_at")
        if (r.get("reopen_count") or 0) < 0:
            raise Reject("invalid_integer", "reopen_count < 0")
    elif source == "csat_surveys":
        score = r.get("score")
        if score is not None and not 1 <= score <= 5:
            raise Reject("score_out_of_range", f"score={score}")
        if r.get("responded_at") is not None and score is None:
            raise Reject("null_required_field", "score (responded survey)")
    elif source == "sales_orders":
        if r["amount"] < 0:
            raise Reject("negative_amount", f"amount={r['amount']}")


def dedupe(source: str, rows: list[tuple[dict, dict]]):
    """rows: [(raw, typed)]. Keep one row per key: newest updated_at, first seen on ties.

    Returns (kept, rejects) where rejects are (raw, reason, detail).
    """
    key = CONTRACTS[source].key
    best: dict[str, tuple[dict, dict]] = {}
    rejects = []
    for raw, typed in rows:
        k = typed[key]
        if k not in best:
            best[k] = (raw, typed)
            continue
        cur_raw, cur = best[k]
        if raw == cur_raw:
            rejects.append((raw, "duplicate_record", "exact duplicate in same delivery"))
        elif typed["updated_at"] > cur["updated_at"]:
            rejects.append((cur_raw, "conflicting_duplicate", "superseded by newer version in same delivery"))
            best[k] = (raw, typed)
        else:
            rejects.append((raw, "conflicting_duplicate", "older version in same delivery"))
    return list(best.values()), rejects
