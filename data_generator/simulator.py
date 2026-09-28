"""Deterministic simulator of a B2B SaaS Customer Care operation.

Every entity's full lifecycle is derived from (seed, entity id), so a snapshot taken at any
`as_of` reveals only the events that have happened by then. Re-running later yields the same
entities with progressed state (new -> open -> resolved -> closed, reopens, CSAT replies),
which is what a live source system looks like to an incremental pipeline.
"""
from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

N_CUSTOMERS_AT_START = 1200
NEW_CUSTOMER_EVERY_DAYS = 0.6
N_AGENTS = 45
BASE_TICKETS_PER_DAY = 125
CLOSE_AFTER_RESOLVED = timedelta(hours=72)

SEGMENTS = [("SMB", 0.60), ("Mid-Market", 0.30), ("Enterprise", 0.10)]
SEGMENT_TICKET_WEIGHT = {"SMB": 1.0, "Mid-Market": 2.2, "Enterprise": 5.0}
PLAN_BY_SEGMENT = {
    "SMB": [("starter", 0.65), ("professional", 0.35)],
    "Mid-Market": [("professional", 0.45), ("business", 0.55)],
    "Enterprise": [("business", 0.15), ("enterprise", 0.85)],
}
PLAN_UPGRADE = {"starter": "professional", "professional": "business", "business": "enterprise"}
PLAN_MRR = {"starter": 49.0, "professional": 199.0, "business": 799.0, "enterprise": 3900.0}
REGIONS = {
    "North America": (0.45, ["United States", "Canada"]),
    "EMEA": (0.30, ["United Kingdom", "Germany", "France", "Netherlands", "Sweden"]),
    "APAC": (0.20, ["Australia", "Singapore", "Japan", "Vietnam", "India"]),
    "LATAM": (0.05, ["Brazil", "Mexico", "Chile"]),
}
INDUSTRIES = ["Retail", "Healthcare", "Fintech", "Logistics", "Education", "Manufacturing",
              "Media", "Travel", "Real Estate", "Software"]
COMPANY_A = ["Blue", "North", "Bright", "Summit", "Iron", "Silver", "Rapid", "Green", "Apex",
             "Nova", "Clear", "Harbor", "Pioneer", "Vertex", "Golden", "Atlas", "Crystal",
             "Urban", "Prime", "Solar", "Red", "Maple", "Quantum", "Coastal", "Evergreen"]
COMPANY_B = ["Labs", "Logistics", "Health", "Retail", "Systems", "Foods", "Analytics",
             "Partners", "Networks", "Works", "Studios", "Supply", "Dynamics", "Group",
             "Solutions", "Market", "Motors", "Energy", "Finance", "Clinics"]
COMPANY_SUFFIX = ["Inc", "LLC", "Ltd", "GmbH", "Co", "Pty Ltd", "SAS", ""]
FIRST_NAMES = ["Anna", "Ben", "Carla", "David", "Elena", "Farid", "Grace", "Hiro", "Ines",
               "James", "Kim", "Liam", "Maya", "Nam", "Olivia", "Pablo", "Quinn", "Rosa",
               "Sam", "Thao", "Uma", "Victor", "Wei", "Yara", "Zoe", "Minh", "Sofia", "Lucas"]
LAST_NAMES = ["Nguyen", "Smith", "Garcia", "Muller", "Tanaka", "Silva", "Kowalski", "Brown",
              "Tran", "Martin", "Rossi", "Johansson", "Patel", "Kim", "Lopez", "Dubois",
              "Wilson", "Le", "Schmidt", "Chen", "Novak", "Haddad", "Okafor", "Pham"]
ACCOUNT_MANAGERS = ["Rachel Green", "Tom Baker", "Lan Pham", "Marco Bellini", "Aisha Khan",
                    "Jonas Berg"]
SALES_REPS = ["Chris Doyle", "Mai Hoang", "Peter Novak", "Sara Lindqvist", "Diego Ramos",
              "Nora Weiss", "Kenji Sato"]

TEAMS = [("tier_1", 18), ("technical", 12), ("billing", 8), ("tier_2", 7)]

CATEGORIES = {
    "billing": (0.21, ["invoice_question", "refund_request", "payment_failed", "plan_change"]),
    "technical": (0.30, ["login_issue", "bug_report", "integration_error", "performance",
                         "data_sync"]),
    "account": (0.17, ["password_reset", "user_management", "data_export", "sso_setup"]),
    "onboarding": (0.10, ["setup_help", "data_import", "training_request"]),
    "feature_request": (0.08, ["new_feature", "improvement"]),
    "cancellation": (0.05, ["cancel_subscription", "downgrade"]),
    "general_inquiry": (0.09, ["how_to", "pricing_question", "other"]),
}
SUBJECTS = {
    "invoice_question": ["Question about invoice {n}", "Invoice amount looks wrong"],
    "refund_request": ["Requesting refund for duplicate charge", "Refund for unused seats"],
    "payment_failed": ["Card payment failed on renewal", "Payment declined, account at risk"],
    "plan_change": ["Want to change our plan", "Add more seats to subscription"],
    "login_issue": ["Cannot log in", "Users locked out after password change"],
    "bug_report": ["Dashboard shows error 500", "Export button does nothing",
                   "Report totals are incorrect"],
    "integration_error": ["Salesforce sync failing", "Webhook deliveries returning 401",
                          "API rate limit errors"],
    "performance": ["App extremely slow today", "Reports take minutes to load"],
    "data_sync": ["Data missing since yesterday", "Duplicate records after sync"],
    "password_reset": ["Password reset email not received", "Reset link expired"],
    "user_management": ["How to remove a user", "Transfer admin rights"],
    "data_export": ["Need full data export", "GDPR data export request"],
    "sso_setup": ["SSO configuration with Okta", "SAML error on login"],
    "setup_help": ["Help setting up workspace", "Onboarding call request"],
    "data_import": ["CSV import failing", "Migrating data from old tool"],
    "training_request": ["Training session for new team", "Admin training"],
    "new_feature": ["Feature request: custom fields", "Request: dark mode"],
    "improvement": ["Suggestion to improve filters", "Improve mobile experience"],
    "cancel_subscription": ["Please cancel our subscription", "Cancellation request"],
    "downgrade": ["Downgrade to a smaller plan", "Reduce seats"],
    "how_to": ["How do I create a report?", "How to schedule exports"],
    "pricing_question": ["Pricing for 50 seats", "Discount for annual billing?"],
    "other": ["General question", "Question about our account"],
}
PRIORITY_BY_CATEGORY = {
    "billing": {"urgent": 0.03, "high": 0.20, "medium": 0.50, "low": 0.27},
    "technical": {"urgent": 0.08, "high": 0.27, "medium": 0.45, "low": 0.20},
    "account": {"urgent": 0.02, "high": 0.18, "medium": 0.50, "low": 0.30},
    "onboarding": {"urgent": 0.01, "high": 0.15, "medium": 0.54, "low": 0.30},
    "feature_request": {"urgent": 0.00, "high": 0.03, "medium": 0.27, "low": 0.70},
    "cancellation": {"urgent": 0.04, "high": 0.40, "medium": 0.41, "low": 0.15},
    "general_inquiry": {"urgent": 0.00, "high": 0.07, "medium": 0.43, "low": 0.50},
}
SEGMENT_PRIORITY_BOOST = {"SMB": 1.0, "Mid-Market": 1.4, "Enterprise": 2.6}
CHANNELS = {"email": 0.38, "chat": 0.25, "web_form": 0.17, "phone": 0.15, "social": 0.05}
CHANNEL_RESPONSE_MULT = {"phone": 0.35, "chat": 0.5, "email": 1.25, "web_form": 1.2,
                         "social": 1.3}
FIRST_RESPONSE_MEDIAN_MIN = {"urgent": 4.0, "high": 16.0, "medium": 55.0, "low": 120.0}
RESOLUTION_MEDIAN_HOURS = {"urgent": 3.0, "high": 10.0, "medium": 28.0, "low": 55.0}
CATEGORY_RESOLUTION_MULT = {"technical": 1.6, "billing": 0.8, "account": 0.6,
                            "onboarding": 1.2, "feature_request": 2.5, "cancellation": 1.0,
                            "general_inquiry": 0.5}
# Share of daily volume per UTC hour: mostly EMEA + North America business hours.
HOUR_WEIGHTS = [1.0, 0.8, 0.7, 0.7, 0.8, 1.0, 1.6, 2.6, 3.8, 5.0, 5.6, 5.8, 5.6, 5.9, 6.2,
                6.4, 6.1, 5.4, 4.6, 3.8, 3.0, 2.3, 1.7, 1.3]
DOW_FACTOR = [1.30, 1.10, 1.05, 1.0, 0.95, 0.40, 0.30]  # Mon..Sun
CSAT_COMMENTS_GOOD = ["Quick and helpful, thanks!", "Great support as always.",
                      "Problem solved on first reply.", "Very knowledgeable agent."]
CSAT_COMMENTS_BAD = ["Took far too long to get a reply.", "Had to explain the issue twice.",
                     "Issue came back after it was closed.", "Nobody followed up.",
                     "Not resolved, just closed."]


def _rng(seed: int, *parts) -> random.Random:
    return random.Random(":".join(str(p) for p in (seed, *parts)))


def _pick(rng: random.Random, weighted) -> str:
    items = list(weighted.items()) if isinstance(weighted, dict) else list(weighted)
    return rng.choices([k for k, _ in items], weights=[w for _, w in items])[0]


def _lognormal(rng: random.Random, median: float, sigma: float) -> float:
    return math.exp(rng.gauss(math.log(median), sigma))


def _poisson(rng: random.Random, lam: float) -> int:
    if lam > 40:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    threshold, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= threshold:
            return k
        k += 1


@dataclass
class Customer:
    customer_id: str
    idx: int
    company_name: str
    contact_name: str
    email: str | None
    phone: str
    segment: str
    industry: str
    region: str
    country: str
    initial_plan: str
    upgrade_at: datetime | None
    account_manager: str | None
    billing_cycle: str
    signup_at: datetime
    churn_at: datetime | None
    segment_raw: str

    def plan_at(self, ts: datetime) -> str:
        if self.upgrade_at and ts >= self.upgrade_at:
            return PLAN_UPGRADE[self.initial_plan]
        return self.initial_plan

    def is_active_at(self, ts: datetime) -> bool:
        return self.signup_at <= ts and (self.churn_at is None or ts < self.churn_at)


@dataclass
class Agent:
    agent_id: str
    agent_name: str
    email: str
    team: str
    shift: str
    skill: float
    hire_at: datetime
    termination_at: datetime | None

    def is_active_at(self, ts: datetime) -> bool:
        return self.hire_at <= ts and (self.termination_at is None or ts < self.termination_at)


class Simulator:
    def __init__(self, start: datetime, seed: int = 42):
        self.start = start.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        self.seed = seed
        self.agents = self._build_agents()
        self._customers: list[Customer] = []
        self._cum_weights: list[float] = []
        self._signups: list[datetime] = []

    # ---------- customers ----------
    def _customer(self, i: int) -> Customer:
        r = _rng(self.seed, "customer", i)
        segment = _pick(r, SEGMENTS)
        region = _pick(r, {k: v[0] for k, v in REGIONS.items()})
        if i < N_CUSTOMERS_AT_START:
            signup = self.start - timedelta(days=r.uniform(10, 3 * 365))
        else:
            signup = self.start + timedelta(days=(i - N_CUSTOMERS_AT_START) * NEW_CUSTOMER_EVERY_DAYS,
                                            hours=r.uniform(8, 18))
        signup = signup.replace(microsecond=0)
        plan = _pick(r, PLAN_BY_SEGMENT[segment])
        upgrade_at = None
        if plan in PLAN_UPGRADE and r.random() < 0.15:
            upgrade_at = (signup + timedelta(days=r.uniform(60, 500))).replace(microsecond=0)
        churn_at = None
        if r.random() < 0.08:
            churn_at = (signup + timedelta(days=r.uniform(90, 700))).replace(microsecond=0)
        first, last = r.choice(FIRST_NAMES), r.choice(LAST_NAMES)
        name = f"{r.choice(COMPANY_A)} {r.choice(COMPANY_B)}"
        suffix = r.choice(COMPANY_SUFFIX)
        company = f"{name} {suffix}".strip()
        domain = name.lower().replace(" ", "") + ".com"
        seg_raw = segment
        if r.random() < 0.03:  # sloppy CRM entry, fixed in staging, not rejected
            seg_raw = r.choice([segment.upper(), f" {segment.lower()}", f"{segment} "])
        return Customer(
            customer_id=f"CUS-{10000 + i}", idx=i, company_name=company,
            contact_name=f"{first} {last}",
            email=None if r.random() < 0.02 else f"{first.lower()}.{last.lower()}@{domain}",
            phone=f"+{r.randint(1, 99)} {r.randint(100, 999)} {r.randint(100, 999)} {r.randint(1000, 9999)}",
            segment=segment, industry=r.choice(INDUSTRIES), region=region,
            country=r.choice(REGIONS[region][1]), initial_plan=plan, upgrade_at=upgrade_at,
            account_manager=r.choice(ACCOUNT_MANAGERS) if segment != "SMB" else None,
            billing_cycle="annual" if r.random() < {"SMB": 0.15, "Mid-Market": 0.5,
                                                    "Enterprise": 0.85}[segment] else "monthly",
            signup_at=signup, churn_at=churn_at, segment_raw=seg_raw,
        )

    def _ensure_customers(self, as_of: datetime) -> None:
        days = max(0.0, (as_of - self.start).total_seconds() / 86400)
        n = N_CUSTOMERS_AT_START + int(days / NEW_CUSTOMER_EVERY_DAYS) + 1
        if n <= len(self._customers):
            return
        customers = [self._customer(i) for i in range(n)]
        customers.sort(key=lambda c: c.signup_at)
        self._customers = customers
        self._signups = [c.signup_at for c in customers]
        total, cum = 0.0, []
        for c in customers:
            total += SEGMENT_TICKET_WEIGHT[c.segment]
            cum.append(total)
        self._cum_weights = cum

    def customers(self, as_of: datetime) -> list[dict]:
        self._ensure_customers(as_of)
        rows = []
        for c in self._customers:
            if c.signup_at > as_of:
                continue
            events = [c.signup_at] + [t for t in (c.upgrade_at, c.churn_at) if t and t <= as_of]
            rows.append({
                "customer_id": c.customer_id, "company_name": c.company_name,
                "contact_name": c.contact_name, "email": c.email, "phone": c.phone,
                "segment": c.segment_raw, "industry": c.industry, "region": c.region,
                "country": c.country, "plan_tier": c.plan_at(as_of),
                "billing_cycle": c.billing_cycle, "account_manager": c.account_manager,
                "signup_date": c.signup_at.date().isoformat(),
                "is_active": c.is_active_at(as_of),
                "churn_date": c.churn_at.date().isoformat() if c.churn_at and c.churn_at <= as_of else None,
                "updated_at": max(events),
            })
        return rows

    def _pick_customer(self, r: random.Random, ts: datetime) -> Customer:
        k = bisect.bisect_right(self._signups, ts)
        for _ in range(5):
            x = r.random() * self._cum_weights[k - 1]
            c = self._customers[bisect.bisect_left(self._cum_weights, x, 0, k)]
            if c.is_active_at(ts):
                return c
        return c

    # ---------- agents ----------
    def _build_agents(self) -> list[Agent]:
        agents, n, used = [], 0, set()
        for team, size in TEAMS:
            for _ in range(size):
                n += 1
                r = _rng(self.seed, "agent", n)
                first, last = r.choice(FIRST_NAMES), r.choice(LAST_NAMES)
                # Rosters need unique display names; re-draw from a separate stream so r stays untouched.
                k = 0
                while f"{first} {last}" in used:
                    k += 1
                    alt = _rng(self.seed, "agent-name", n, k)
                    first, last = alt.choice(FIRST_NAMES), alt.choice(LAST_NAMES)
                used.add(f"{first} {last}")
                if r.random() < 0.12:
                    hire = self.start + timedelta(days=r.uniform(20, 150))
                    skill = r.uniform(1.15, 1.5)  # new hires are slower
                else:
                    hire = self.start - timedelta(days=r.uniform(90, 1500))
                    skill = r.uniform(0.7, 1.2)
                term = None
                if r.random() < 0.07:
                    term = self.start + timedelta(days=r.uniform(30, 170))
                agents.append(Agent(
                    agent_id=f"AGT-{n:03d}", agent_name=f"{first} {last}",
                    email=f"{first.lower()}.{last.lower()}{n}@support.example.com", team=team,
                    shift=_pick(r, {"day": 0.6, "evening": 0.28, "night": 0.12}),
                    skill=round(skill, 3), hire_at=hire.replace(microsecond=0),
                    termination_at=term.replace(microsecond=0) if term else None,
                ))
        return agents

    def agent_rows(self, as_of: datetime) -> list[dict]:
        rows = []
        for a in self.agents:
            if a.hire_at > as_of:
                continue
            terminated = a.termination_at is not None and a.termination_at <= as_of
            rows.append({
                "agent_id": a.agent_id, "agent_name": a.agent_name, "email": a.email,
                "team": a.team, "shift": a.shift, "hire_date": a.hire_at.date().isoformat(),
                "termination_date": a.termination_at.date().isoformat() if terminated else None,
                "is_active": not terminated,
                "updated_at": a.termination_at if terminated else a.hire_at,
            })
        return rows

    def _pick_agent(self, r: random.Random, team: str, ts: datetime) -> Agent:
        pool = [a for a in self.agents if a.team == team and a.is_active_at(ts)]
        if not pool:
            pool = [a for a in self.agents if a.is_active_at(ts)]
        return r.choice(pool)

    # ---------- tickets ----------
    def _is_incident(self, day: int, hour: int) -> bool:
        return day % 53 == 37 and 13 <= hour <= 19

    def _expected_per_hour(self, ts: datetime, with_incident: bool = True) -> float:
        day = (ts - self.start).days
        growth = 1 + 0.35 * min(day, 365) / 180
        lam = BASE_TICKETS_PER_DAY * growth * DOW_FACTOR[ts.weekday()] * HOUR_WEIGHTS[ts.hour] / sum(HOUR_WEIGHTS)
        if with_incident and self._is_incident(day, ts.hour):
            lam *= 3.5
        return lam

    def _ticket_lifecycles(self, as_of: datetime):
        self._ensure_customers(as_of)
        hours = int((as_of - self.start).total_seconds() // 3600) + 1
        number = 100000
        for h in range(hours):
            hour_start = self.start + timedelta(hours=h)
            hr = _rng(self.seed, "hour", h)
            lam = self._expected_per_hour(hour_start)
            count = _poisson(hr, lam)
            load = max(1.0, count / (1.15 * self._expected_per_hour(hour_start, False) + 1))
            incident = self._is_incident((hour_start - self.start).days, hour_start.hour)
            for _ in range(count):
                number += 1
                created = hour_start + timedelta(seconds=hr.randrange(3600))
                if created > as_of:
                    continue
                yield self._lifecycle(number, created, load, incident)

    def _lifecycle(self, number: int, created: datetime, load: float, incident: bool) -> dict:
        r = _rng(self.seed, "ticket", number)
        customer = self._pick_customer(r, created)
        if incident and r.random() < 0.7:
            category = "technical"
            sub = r.choice(["performance", "bug_report", "data_sync"])
        else:
            category = _pick(r, {k: v[0] for k, v in CATEGORIES.items()})
            sub = r.choice(CATEGORIES[category][1])
        pw = dict(PRIORITY_BY_CATEGORY[category])
        boost = SEGMENT_PRIORITY_BOOST[customer.segment]
        pw["urgent"] *= boost
        pw["high"] *= math.sqrt(boost)
        if incident:
            pw["urgent"] *= 2.5
        priority = _pick(r, pw)
        cw = dict(CHANNELS)
        if priority == "urgent":
            cw["phone"] *= 3
            cw["chat"] *= 1.5
        channel = _pick(r, cw)
        if category in ("billing", "cancellation"):
            team = "billing"
        elif category == "technical":
            team = "tier_2" if priority == "urgent" and customer.segment == "Enterprise" and r.random() < 0.5 else "technical"
        else:
            team = "tier_1"
        agent = self._pick_agent(r, team, created)

        off_hours = created.hour < 7 or created.hour >= 21
        weekend = created.weekday() >= 5
        mult = CHANNEL_RESPONSE_MULT[channel] * agent.skill * load
        mult *= 1.8 if off_hours else 1.0
        mult *= 1.5 if weekend else 1.0
        frt_min = max(0.5, _lognormal(r, FIRST_RESPONSE_MEDIAN_MIN[priority] * mult, 0.75))
        first_response = created + timedelta(minutes=frt_min)

        if channel in ("phone", "chat") and r.random() < 0.3:
            res_hours = r.uniform(0.05, 0.5)
        else:
            res_hours = _lognormal(r, RESOLUTION_MEDIAN_HOURS[priority] * CATEGORY_RESOLUTION_MULT[category], 0.9)
        resolved1 = first_response + timedelta(hours=res_hours)

        p_reopen = 0.05 + (0.04 if category == "technical" else 0) + (0.03 if res_hours < 1 else 0)
        reopened_at = resolved2 = None
        if r.random() < p_reopen:
            reopened_at = resolved1 + timedelta(hours=_lognormal(r, 20, 0.8))
            resolved2 = reopened_at + timedelta(hours=_lognormal(r, 8, 0.9))
        final_resolved = resolved2 or resolved1
        waiting_state = "on_hold" if category == "technical" and r.random() < 0.12 else (
            "pending" if r.random() < 0.35 else "open")
        breach_target = {"urgent": 15, "high": 60, "medium": 240, "low": 480}[priority]

        # CSAT survey goes out on first resolution, answer may arrive after a reopen.
        survey = None
        breached = frt_min > breach_target
        p_respond = 0.33 + (0.10 if breached else 0)
        if r.random() < p_respond:
            lag = timedelta(hours=_lognormal(r, 6, 1.1))
            p_sat = 0.88 - 0.30 * breached - 0.25 * (reopened_at is not None) \
                - 0.10 * ((final_resolved - created) > timedelta(hours=72)) - 0.05 * (channel == "social")
            if r.random() < p_sat:
                score = 5 if r.random() < 0.6 else 4
                comment = r.choice(CSAT_COMMENTS_GOOD) if r.random() < 0.35 else None
            else:
                score = _pick(r, {1: 0.3, 2: 0.35, 3: 0.35})
                comment = r.choice(CSAT_COMMENTS_BAD) if r.random() < 0.6 else None
            survey = {"lag": lag, "score": score, "comment": comment}

        return {
            "ticket_id": f"TCK-{number}", "number": number, "customer": customer, "agent": agent,
            "category": category, "subcategory": sub, "priority": priority, "channel": channel,
            "subject": r.choice(SUBJECTS[sub]).format(n=r.randint(10000, 99999)),
            "created_at": created.replace(microsecond=0),
            "first_response_at": first_response.replace(microsecond=0),
            "resolved1": resolved1.replace(microsecond=0),
            "reopened_at": reopened_at.replace(microsecond=0) if reopened_at else None,
            "resolved2": resolved2.replace(microsecond=0) if resolved2 else None,
            "waiting_state": waiting_state, "survey": survey,
        }

    @staticmethod
    def _ticket_state(t: dict, as_of: datetime) -> dict:
        created, fr, r1 = t["created_at"], t["first_response_at"], t["resolved1"]
        reopened, r2 = t["reopened_at"], t["resolved2"]
        events = [created]
        first_response_at = resolved_at = closed_at = reopened_at = None
        reopen_count = 0
        if fr > as_of:
            status = "new"
        else:
            first_response_at = fr
            events.append(fr)
            if r1 > as_of:
                status = t["waiting_state"]
            elif reopened is None or reopened > as_of:
                resolved_at = r1
                events.append(r1)
                closed = r1 + CLOSE_AFTER_RESOLVED
                status = "resolved"
                if reopened is None and closed <= as_of:
                    status, closed_at = "closed", closed
                    events.append(closed)
            else:
                reopened_at, reopen_count = reopened, 1
                events += [r1, reopened]
                if r2 > as_of:
                    status = "open"
                else:
                    resolved_at = r2
                    events.append(r2)
                    closed = r2 + CLOSE_AFTER_RESOLVED
                    status = "resolved"
                    if closed <= as_of:
                        status, closed_at = "closed", closed
                        events.append(closed)
        return {
            "ticket_id": t["ticket_id"], "customer_id": t["customer"].customer_id,
            "agent_id": t["agent"].agent_id, "subject": t["subject"],
            "category": t["category"], "subcategory": t["subcategory"],
            "priority": t["priority"], "channel": t["channel"], "status": status,
            "created_at": created, "first_response_at": first_response_at,
            "resolved_at": resolved_at, "closed_at": closed_at, "reopened_at": reopened_at,
            "reopen_count": reopen_count, "updated_at": max(events),
        }

    def snapshot(self, as_of: datetime) -> dict[str, list[dict]]:
        as_of = as_of.astimezone(UTC).replace(microsecond=0)
        tickets, surveys = [], []
        for t in self._ticket_lifecycles(as_of):
            tickets.append(self._ticket_state(t, as_of))
            s = t["survey"]
            if s is None or t["resolved1"] > as_of:
                continue
            responded = t["resolved1"] + s["lag"]
            answered = responded <= as_of
            surveys.append({
                "survey_id": f"CSAT-{t['number']}", "ticket_id": t["ticket_id"],
                "customer_id": t["customer"].customer_id,
                "sent_at": t["resolved1"],
                "responded_at": responded.replace(microsecond=0) if answered else None,
                "score": s["score"] if answered else None,
                "comment": s["comment"] if answered else None,
                "updated_at": responded.replace(microsecond=0) if answered else t["resolved1"],
            })
        return {
            "customers": self.customers(as_of),
            "agents": self.agent_rows(as_of),
            "tickets": tickets,
            "csat_surveys": surveys,
            "sales_orders": self.sales_orders(as_of),
        }

    # ---------- sales ----------
    def sales_orders(self, as_of: datetime) -> list[dict]:
        self._ensure_customers(as_of)
        horizon = self.start - timedelta(days=180)
        rows = []
        for c in self._customers:
            if c.signup_at > as_of:
                continue
            r = _rng(self.seed, "orders", c.idx)
            step = 365 if c.billing_cycle == "annual" else 30
            order_date = c.signup_at
            n, prev_plan = 0, None
            while order_date <= as_of and (c.churn_at is None or order_date < c.churn_at):
                plan = c.plan_at(order_date)
                n += 1
                if order_date >= horizon:
                    if prev_plan is None and n == 1:
                        order_type = "new"
                    elif prev_plan and plan != prev_plan:
                        order_type = "upgrade"
                    else:
                        order_type = "renewal"
                    months = 12 if c.billing_cycle == "annual" else 1
                    discount = 0.85 if c.billing_cycle == "annual" else 1.0
                    seats_factor = r.uniform(0.8, 1.6) if c.segment != "SMB" else 1.0
                    amount = round(PLAN_MRR[plan] * months * discount * seats_factor, 2)
                    status = _pick(r, {"paid": 0.95, "failed": 0.03, "refunded": 0.02})
                    updated = order_date
                    if status == "refunded":
                        updated = order_date + timedelta(days=r.uniform(1, 20))
                        if updated > as_of:
                            status, updated = "paid", order_date
                    rows.append({
                        "order_id": f"SO-{c.idx:05d}-{n:03d}", "customer_id": c.customer_id,
                        "order_date": order_date.date().isoformat(), "plan": plan,
                        "order_type": order_type, "billing_cycle": c.billing_cycle,
                        "amount": amount, "currency": "USD", "status": status,
                        "sales_rep": r.choice(SALES_REPS), "updated_at": updated.replace(microsecond=0),
                    })
                prev_plan = plan
                order_date = order_date + timedelta(days=step)
        return rows


def parse_start(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC)
