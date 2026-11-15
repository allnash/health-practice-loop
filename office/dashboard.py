"""Home page of the admin: the office at a glance."""

import json
import re
from datetime import date

from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from .models import Decision, LoopRun, Routine
from .services import build_snapshot, workload

STATUS_LABELS = {
    "attention": ("Needs attention", "danger"),
    "due": ("Work due", "warning"),
    "ok": ("On track", "success"),
}


def _label(text: str, variant: str) -> str:
    return render_to_string("unfold/helpers/label.html", {"text": text, "variant": variant})


def _link(text: str, model: str, pk: int | None = None, query: str = "") -> str:
    if pk is None:
        url = reverse(f"admin:office_{model}_changelist") + query
    else:
        url = reverse(f"admin:office_{model}_change", args=[pk])
    return format_html('<a href="{}" class="text-primary-600 underline">{}</a>', url, text)


def _day(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%b %d").replace(" 0", " ") if iso else "No date"


def _count(count: int, late: int) -> str:
    if late:
        return format_html("{} <span class=\"text-red-600\">({} late)</span>", count, late)
    return str(count)


def render_summary(text: str) -> str:
    """Show a loop summary's bold headings and bullets without a Markdown library."""
    blocks, bullets = [], []

    def flush():
        if bullets:
            blocks.append('<ul class="pl-5 mb-2" style="list-style: disc">' + "".join(bullets) + "</ul>")
            bullets.clear()

    for line in text.splitlines():
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escape(line.strip()))
        if line.startswith("- "):
            bullets.append(f"<li>{line[2:]}</li>")
            continue
        flush()
        if line:
            blocks.append(f'<p class="mb-1">{line}</p>')
    flush()
    return mark_safe("".join(blocks))


def workload_chart(days: int = 14) -> str:
    data = workload(days=days)
    return json.dumps(
        {
            "labels": data["labels"],
            "datasets": [
                {"label": "Routines", "data": data["routines"], "backgroundColor": "var(--color-primary-700)"},
                {"label": "Tasks", "data": data["tasks"], "backgroundColor": "var(--color-primary-400)"},
                {"label": "Deadlines", "data": data["deadlines"], "backgroundColor": "var(--color-primary-200)"},
            ],
        }
    )


def dashboard_callback(request, context):
    snapshot = build_snapshot()
    totals = snapshot["totals"]

    cards = [
        {
            "title": "Routines due",
            "value": totals["routines_due_today"] + totals["routines_overdue"],
            "note": f"{totals['routines_overdue']} overdue",
            "alert": totals["routines_overdue"] > 0,
            "href": reverse("admin:office_routine_changelist"),
        },
        {
            "title": "Open tasks",
            "value": totals["tasks_open"],
            "note": f"{totals['tasks_overdue']} overdue",
            "alert": totals["tasks_overdue"] > 0,
            "href": reverse("admin:office_task_changelist") + "?status__exact=todo",
        },
        {
            "title": "Deadlines coming up",
            "value": totals["deadlines_flagged"],
            "note": f"{totals['deadlines_overdue']} past due",
            "alert": totals["deadlines_overdue"] > 0,
            "href": reverse("admin:office_deadline_changelist"),
        },
        {
            "title": "Decisions waiting on you",
            "value": totals["decisions_open"],
            "note": f"{totals['metrics_missing']} metrics need this period's number",
            "alert": False,
            "href": reverse("admin:office_decision_changelist") + "?status__exact=open",
        },
    ]

    functions_table = {
        "headers": ["Function", "Owner", "Status", "Routines due", "Open tasks", "Deadlines", "Decisions"],
        "rows": [
            [
                _link(row["name"], "function", row["id"]),
                row["owner"] or _label("Unassigned", "info"),
                _label(*STATUS_LABELS[row["status"]]),
                _count(row["routines_due"], row["routines_overdue"]),
                _count(row["tasks_open"], row["tasks_overdue"]),
                _count(row["deadlines_flagged"], row["deadlines_overdue"]),
                row["decisions_open"],
            ]
            for row in snapshot["functions"]
        ],
    }

    routines_table = {
        "headers": ["Routine", "Function", "Due", "Responsible"],
        "rows": [
            [
                _link(item["title"], "routine", item["id"]),
                item["function"],
                _label(f"{item['days_late']}d late", "danger") if item["days_late"] else "Today",
                item["owner"] or "Unassigned",
            ]
            for item in snapshot["routines"][:12]
        ],
    }

    tasks_table = {
        "headers": ["Task", "Function", "Due", "Owner"],
        "rows": [
            [
                _link(item["title"], "task", item["id"]),
                item["function"],
                _label("Blocked", "danger")
                if item["blocked"]
                else _label(f"Late · {_day(item['due'])}", "danger")
                if item["overdue"]
                else _day(item["due"]),
                item["owner"] or "Unassigned",
            ]
            for item in snapshot["tasks"][:12]
        ],
    }

    deadlines_table = {
        "headers": ["Deadline", "Type", "Due", "Time left"],
        "rows": [
            [
                _link(item["title"], "deadline", item["id"]),
                item["kind"],
                _day(item["due"]),
                _label(f"{-item['days_left']}d past due", "danger")
                if item["days_left"] < 0
                else _label(f"{item['days_left']}d", "warning" if item["days_left"] <= 30 else "info"),
            ]
            for item in snapshot["deadlines"][:12]
        ],
    }

    metrics_table = {
        "headers": ["Metric", "Function", "Latest", "Target", "Status"],
        "rows": [
            [
                _link(item["name"], "metric", item["id"]),
                item["function"],
                f"{item['latest_value']:g} {item['unit']}".strip()
                if item["latest_value"] is not None
                else "—",
                f"{item['target']:g} {item['unit']}".strip() if item["target"] is not None else "—",
                _label("Not reported", "info")
                if item["latest_value"] is None
                else _label("Needs this period", "warning")
                if item["missing"]
                else _label("Off target", "danger")
                if item["on_target"] is False
                else _label("On target", "success")
                if item["on_target"]
                else _label("Reported", "info"),
            ]
            for item in snapshot["metrics"]
        ],
    }

    decisions_table = {
        "headers": ["Decision", "Function", "Waiting"],
        "rows": [
            [
                _link(item["question"], "decision", item["id"]),
                item["function"] or "—",
                f"{item['waiting_days']}d",
            ]
            for item in snapshot["decisions"][:8]
        ],
    }

    context.update(
        {
            "office_cards": cards,
            "office_functions": functions_table,
            "office_routines": routines_table,
            "office_tasks": tasks_table,
            "office_deadlines": deadlines_table,
            "office_metrics": metrics_table,
            "office_decisions": decisions_table,
            "office_last_run": (last_run := LoopRun.objects.first()),
            "office_last_run_summary": render_summary(last_run.summary) if last_run else "",
            "office_workload": workload_chart(),
            "office_more_routines": max(len(snapshot["routines"]) - 12, 0),
        }
    )
    return context


def routines_badge(request):
    due = Routine.objects.filter(
        is_active=True, function__is_active=True, next_due__lte=timezone.localdate()
    )
    return due.count() or None


def decisions_badge(request):
    return Decision.objects.filter(status=Decision.Status.OPEN).count() or None
