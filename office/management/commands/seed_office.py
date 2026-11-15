"""Create the starter board: functions, their usual routines, metric definitions
and a few setup tasks. Safe to run again; it only adds what is missing.

No numbers, dates of real obligations or targets are invented here. Those are
the practice's own and are entered through the admin.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from office.models import Function, Metric, Routine, Task, add_months

MON, TUE, WED, THU, FRI = range(5)

# (function, description, routines, metrics)
# A routine is (title, cadence, anchor): a weekday for weekly, a day of month for
# monthly and quarterly, (month, day) for yearly, and None for every weekday.
# A metric is (name, unit, period, direction).
STARTER = [
    (
        "Front desk & scheduling",
        "Calendars, confirmations, the waitlist and every message that reaches the office.",
        [
            ("Confirm tomorrow's appointments and fill cancellations from the waitlist", "daily", None),
            ("Clear voicemail, portal messages and the shared inbox", "daily", None),
            ("Review next week's schedule for gaps and double bookings", "weekly", FRI),
        ],
        [
            ("Appointments held", "count", "weekly", "higher"),
            ("No-show and late-cancel rate", "%", "weekly", "lower"),
        ],
    ),
    (
        "Intake & referrals",
        "From first inquiry to a booked first appointment, and the people who refer.",
        [
            ("Respond to every new inquiry within one business day", "daily", None),
            ("Follow up on inquiries that have not booked an intake", "weekly", MON),
            ("Thank and update the referral sources that sent people this month", "monthly", 5),
        ],
        [
            ("New client inquiries", "count", "weekly", "higher"),
            ("Intakes booked", "count", "weekly", "higher"),
            ("Days from inquiry to first appointment", "days", "weekly", "lower"),
        ],
    ),
    (
        "Billing & insurance",
        "Eligibility, claims, payments, denials and client balances.",
        [
            ("Verify insurance eligibility for the next two days of appointments", "daily", None),
            ("Submit claims and post payments", "weekly", TUE),
            ("Work denied and rejected claims", "weekly", THU),
            ("Send client statements and review balances over 60 days", "monthly", 3),
        ],
        [
            ("Claims submitted", "count", "weekly", "higher"),
            ("Claim denial rate", "%", "monthly", "lower"),
            ("Days in accounts receivable", "days", "monthly", "lower"),
            ("Client balances over 60 days", "$", "monthly", "lower"),
        ],
    ),
    (
        "Credentialing & licensing",
        "Clinician licenses, CAQH, payer enrollment and malpractice coverage.",
        [
            ("Check license, CAQH and payer recredentialing dates against Deadlines", "monthly", 1),
            ("Re-attest CAQH profiles", "quarterly", 1),
        ],
        [],
    ),
    (
        "Compliance & privacy",
        "HIPAA, access to records, required training and policies.",
        [
            ("Review who has access to the EHR and shared drives", "monthly", 10),
            ("Spot-check documentation timeliness with the clinical lead", "quarterly", 15),
            ("Run the security risk assessment and staff privacy training", "yearly", (1, 15)),
        ],
        [],
    ),
    (
        "People & payroll",
        "Staff schedules, time off, payroll inputs, onboarding and offboarding.",
        [
            ("Confirm payroll inputs: hours, changes and new hires", "weekly", MON),
            ("Review time off and coverage for the coming month", "monthly", 20),
        ],
        [("Clinician caseload utilization", "%", "weekly", "higher")],
    ),
    (
        "Facilities & supplies",
        "The space itself: supplies, repairs, cleaning, safety and sound privacy.",
        [
            ("Check supplies and reorder", "weekly", FRI),
            ("Walk the space: safety, repairs, cleanliness, sound privacy", "monthly", 15),
        ],
        [],
    ),
    (
        "Technology & vendors",
        "EHR, phones, devices, subscriptions and the agreements behind them.",
        [
            ("Confirm backups, software updates and device encryption", "monthly", 12),
            ("Review subscriptions, seats and vendor agreements, including BAAs", "quarterly", 20),
        ],
        [],
    ),
    (
        "Finance & reporting",
        "Bank and card accounts, the weekly numbers, taxes and the accountant.",
        [
            ("Enter last week's numbers into Metrics", "weekly", MON),
            ("Reconcile bank and card accounts and review the month with the owner", "monthly", 8),
            ("Prepare estimated tax and quarterly filings with the accountant", "quarterly", 5),
        ],
        [("Collections", "$", "weekly", "higher")],
    ),
    (
        "Marketing & outreach",
        "Directory profiles, the website, reviews and where new inquiries come from.",
        [
            ("Update directory profiles and whether clinicians are accepting new clients", "weekly", WED),
            ("Review where new inquiries came from and reply to public reviews", "monthly", 18),
        ],
        [],
    ),
]

# (function, title, details)
SETUP_TASKS = [
    (
        "People & payroll",
        "Add staff as users and give every function an owner",
        "Each function on the dashboard shows who answers for it. Unowned functions are flagged.",
    ),
    (
        "Front desk & scheduling",
        "Review the starter routines: remove what does not apply, add what is missing",
        "The routines came from a generic checklist for an outpatient practice. Make them yours.",
    ),
    (
        "Credentialing & licensing",
        "Enter every license, CAQH, malpractice and payer recredentialing date into Deadlines",
        "One deadline per clinician per obligation. Set how many months until it recurs.",
    ),
    (
        "Technology & vendors",
        "Enter lease, insurance policy, software and vendor renewal dates into Deadlines",
        "Include business associate agreements with the EHR and any billing or phone vendor.",
    ),
    (
        "Finance & reporting",
        "Set a target for each metric",
        "Until a metric has a target the dashboard can only show its value, not whether it is good.",
    ),
    (
        "Finance & reporting",
        "Enter the last four weeks of numbers into Metrics",
        "Counts and rates only. This gives the loop a baseline to compare against.",
    ),
]


def first_due(cadence: str, anchor, today: date) -> date:
    if cadence == "daily":
        return today if today.weekday() < 5 else today + timedelta(days=7 - today.weekday())
    if cadence == "weekly":
        return today + timedelta(days=(anchor - today.weekday()) % 7)
    if cadence == "yearly":
        month, day = anchor
        candidate = date(today.year, month, day)
        return candidate if candidate >= today else date(today.year + 1, month, day)
    candidate = today.replace(day=anchor)
    if candidate < today:
        candidate = add_months(candidate, 1)
    if cadence == "quarterly":
        while candidate.month not in (1, 4, 7, 10):
            candidate = add_months(candidate, 1)
    return candidate


class Command(BaseCommand):
    help = __doc__

    def handle(self, *args, **options):
        today = timezone.localdate()
        created = {"functions": 0, "routines": 0, "metrics": 0, "tasks": 0}

        for order, (name, description, routines, metrics) in enumerate(STARTER, start=1):
            function, was_created = Function.objects.get_or_create(
                slug=slugify(name),
                defaults={"name": name, "description": description, "order": order},
            )
            created["functions"] += was_created
            for title, cadence, anchor in routines:
                _, was_created = Routine.objects.get_or_create(
                    function=function,
                    title=title,
                    defaults={"cadence": cadence, "next_due": first_due(cadence, anchor, today)},
                )
                created["routines"] += was_created
            for metric_name, unit, period, direction in metrics:
                _, was_created = Metric.objects.get_or_create(
                    function=function,
                    name=metric_name,
                    defaults={"unit": unit, "period": period, "direction": direction},
                )
                created["metrics"] += was_created

        for function_name, title, details in SETUP_TASKS:
            _, was_created = Task.objects.get_or_create(
                function=Function.objects.get(slug=slugify(function_name)),
                title=title,
                defaults={
                    "details": details,
                    "priority": Task.Priority.HIGH,
                    "due_date": today + timedelta(days=7),
                },
            )
            created["tasks"] += was_created

        self.stdout.write(
            self.style.SUCCESS("Added " + ", ".join(f"{count} {kind}" for kind, count in created.items()))
        )
