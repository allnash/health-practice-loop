"""The office's current state, computed once for both the dashboard and the loop."""

from datetime import date, timedelta

from django.utils import timezone

from .models import Deadline, Decision, Function, Metric, Routine, Task


def _person(user) -> str | None:
    if user is None:
        return None
    return user.get_full_name() or user.get_username()


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def build_snapshot(today: date | None = None) -> dict:
    """Everything that is due, late, coming up or missing, as plain JSON data.

    Only counts, titles and dates of office work are included. Nothing here
    describes a client.
    """
    today = today or timezone.localdate()
    week_ahead = today + timedelta(days=7)

    functions = list(Function.objects.filter(is_active=True).select_related("owner"))
    rows = {
        function.id: {
            "id": function.id,
            "name": function.name,
            "slug": function.slug,
            "owner": _person(function.owner),
            "routines_due": 0,
            "routines_overdue": 0,
            "tasks_open": 0,
            "tasks_overdue": 0,
            "deadlines_flagged": 0,
            "deadlines_overdue": 0,
            "decisions_open": 0,
            "metrics_missing": 0,
            "metrics_off_target": 0,
        }
        for function in functions
    }

    routines = []
    for routine in Routine.objects.filter(
        is_active=True, function__is_active=True, next_due__lte=today
    ).select_related("function", "owner", "function__owner"):
        overdue = routine.next_due < today
        rows[routine.function_id]["routines_due"] += 1
        rows[routine.function_id]["routines_overdue"] += overdue
        routines.append(
            {
                "id": routine.id,
                "title": routine.title,
                "function": routine.function.name,
                "cadence": routine.get_cadence_display(),
                "owner": _person(routine.responsible),
                "due": _iso(routine.next_due),
                "days_late": (today - routine.next_due).days,
            }
        )

    tasks = []
    for task in (
        Task.objects.exclude(status=Task.Status.DONE)
        .filter(function__is_active=True)
        .select_related("function", "owner")
    ):
        overdue = task.due_date is not None and task.due_date < today
        rows[task.function_id]["tasks_open"] += 1
        rows[task.function_id]["tasks_overdue"] += overdue
        if overdue or task.status == Task.Status.BLOCKED or (
            task.due_date is not None and task.due_date <= week_ahead
        ):
            tasks.append(
                {
                    "id": task.id,
                    "title": task.title,
                    "function": task.function.name,
                    "status": task.get_status_display(),
                    "priority": task.get_priority_display(),
                    "owner": _person(task.owner),
                    "due": _iso(task.due_date),
                    "overdue": overdue,
                    "blocked": task.status == Task.Status.BLOCKED,
                }
            )
    tasks.sort(key=lambda item: (item["due"] is None, item["due"] or ""))

    deadlines = []
    deadline_count = 0
    for deadline in Deadline.objects.filter(
        is_closed=False, function__is_active=True
    ).select_related("function", "owner"):
        deadline_count += 1
        if deadline.flag_from > today:
            continue
        overdue = deadline.due_date < today
        rows[deadline.function_id]["deadlines_flagged"] += 1
        rows[deadline.function_id]["deadlines_overdue"] += overdue
        deadlines.append(
            {
                "id": deadline.id,
                "title": deadline.title,
                "function": deadline.function.name,
                "kind": deadline.get_kind_display(),
                "owner": _person(deadline.owner),
                "due": _iso(deadline.due_date),
                "days_left": (deadline.due_date - today).days,
            }
        )
    deadlines.sort(key=lambda item: item["due"])

    decisions = []
    for decision in Decision.objects.filter(status=Decision.Status.OPEN).select_related("function"):
        if decision.function_id in rows:
            rows[decision.function_id]["decisions_open"] += 1
        decisions.append(
            {
                "id": decision.id,
                "question": decision.question,
                "function": decision.function.name if decision.function else None,
                "recommendation": decision.recommendation,
                "waiting_days": (today - timezone.localdate(decision.created_at)).days,
            }
        )

    metrics = []
    for metric in (
        Metric.objects.filter(is_active=True, function__is_active=True)
        .select_related("function")
        .prefetch_related("entries")
    ):
        entries = list(metric.entries.all())  # newest first, from the prefetch
        latest = entries[0] if entries else None
        expected = metric.latest_complete_period_start(today)
        missing = latest is None or latest.period_start < expected
        on_target = metric.meets_target(latest.value) if latest else None
        rows[metric.function_id]["metrics_missing"] += missing
        rows[metric.function_id]["metrics_off_target"] += on_target is False
        metrics.append(
            {
                "id": metric.id,
                "name": metric.name,
                "function": metric.function.name,
                "unit": metric.unit,
                "period": metric.get_period_display(),
                "direction": metric.direction,
                "target": float(metric.target) if metric.target is not None else None,
                "latest_value": float(latest.value) if latest else None,
                "latest_period": _iso(latest.period_start) if latest else None,
                "previous_value": float(entries[1].value) if len(entries) > 1 else None,
                "expected_period": _iso(expected),
                "missing": missing,
                "on_target": on_target,
            }
        )

    for row in rows.values():
        late = row["routines_overdue"] + row["tasks_overdue"] + row["deadlines_overdue"]
        waiting = row["routines_due"] + row["deadlines_flagged"] + row["decisions_open"]
        row["status"] = "attention" if late else "due" if waiting else "ok"

    function_rows = list(rows.values())
    return {
        "as_of": today.isoformat(),
        "totals": {
            "routines_due_today": sum(1 for r in routines if r["days_late"] == 0),
            "routines_overdue": sum(1 for r in routines if r["days_late"] > 0),
            "tasks_open": sum(r["tasks_open"] for r in function_rows),
            "tasks_overdue": sum(r["tasks_overdue"] for r in function_rows),
            "deadlines_flagged": len(deadlines),
            "deadlines_overdue": sum(1 for d in deadlines if d["days_left"] < 0),
            "decisions_open": len(decisions),
            "metrics_missing": sum(1 for m in metrics if m["missing"]),
            "metrics_off_target": sum(1 for m in metrics if m["on_target"] is False),
        },
        "functions": function_rows,
        "routines": routines,
        "tasks": tasks,
        "deadlines": deadlines,
        "decisions": decisions,
        "metrics": metrics,
        "gaps": {
            "functions_without_owner": [r["name"] for r in function_rows if not r["owner"]],
            "metrics_without_target": [m["name"] for m in metrics if m["target"] is None],
            "metrics_never_reported": [m["name"] for m in metrics if m["latest_value"] is None],
            "no_deadlines_entered": deadline_count == 0,
        },
    }


def workload(today: date | None = None, days: int = 14) -> dict:
    """How much work falls on each of the coming days, by kind.

    Routines are projected forward on their own schedule, so an every-weekday
    routine counts once on each weekday in the window. Anything already late is
    counted on the first day.
    """
    today = today or timezone.localdate()
    window = [today + timedelta(days=offset) for offset in range(days)]
    counts = {day: {"routines": 0, "tasks": 0, "deadlines": 0} for day in window}
    last = window[-1]

    for routine in Routine.objects.filter(is_active=True, function__is_active=True, next_due__lte=last):
        occurrence = routine.next_due
        while occurrence <= last:
            counts[max(occurrence, today)]["routines"] += 1
            occurrence = routine._step(occurrence)

    open_tasks = Task.objects.exclude(status=Task.Status.DONE).filter(
        function__is_active=True, due_date__lte=last
    )
    for due in open_tasks.values_list("due_date", flat=True):
        counts[max(due, today)]["tasks"] += 1

    open_deadlines = Deadline.objects.filter(is_closed=False, function__is_active=True, due_date__lte=last)
    for due in open_deadlines.values_list("due_date", flat=True):
        counts[max(due, today)]["deadlines"] += 1

    return {
        "labels": [day.strftime("%a %d") for day in window],
        "routines": [counts[day]["routines"] for day in window],
        "tasks": [counts[day]["tasks"] for day in window],
        "deadlines": [counts[day]["deadlines"] for day in window],
    }


def render_brief(snapshot: dict) -> str:
    """The snapshot as a short Markdown brief, for the loop to read and reason from."""
    totals, gaps = snapshot["totals"], snapshot["gaps"]
    lines = [
        f"# Office state as of {snapshot['as_of']}",
        "",
        f"- Routines: {totals['routines_due_today']} due today, {totals['routines_overdue']} overdue",
        f"- Tasks: {totals['tasks_open']} open, {totals['tasks_overdue']} overdue",
        f"- Deadlines: {totals['deadlines_flagged']} inside their warning window, "
        f"{totals['deadlines_overdue']} past due",
        f"- Decisions waiting on the owner: {totals['decisions_open']}",
        f"- Metrics: {totals['metrics_missing']} missing their latest period, "
        f"{totals['metrics_off_target']} off target",
        "",
        "## By function",
        "",
        "| Function | Owner | Status | Routines due (late) | Open tasks (late) | Deadlines | Decisions |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in snapshot["functions"]:
        lines.append(
            f"| {row['name']} | {row['owner'] or 'unassigned'} | {row['status']} "
            f"| {row['routines_due']} ({row['routines_overdue']}) "
            f"| {row['tasks_open']} ({row['tasks_overdue']}) "
            f"| {row['deadlines_flagged']} | {row['decisions_open']} |"
        )

    def section(title, items, describe):
        lines.extend(["", f"## {title}", ""])
        lines.extend([f"- {describe(item)}" for item in items] or ["- None"])

    section(
        "Routines due",
        snapshot["routines"],
        lambda r: f"[{r['function']}] {r['title']} — due {r['due']}"
        + (f", {r['days_late']} day(s) late" if r["days_late"] > 0 else "")
        + f" — {r['owner'] or 'unassigned'}",
    )
    section(
        "Tasks needing attention (late, blocked or due within 7 days)",
        snapshot["tasks"],
        lambda t: f"[{t['function']}] {t['title']} — {t['status']}, {t['priority']} priority, "
        f"due {t['due'] or 'no date'}" + (" (late)" if t["overdue"] else "")
        + f" — {t['owner'] or 'unassigned'}",
    )
    section(
        "Deadlines inside their warning window",
        snapshot["deadlines"],
        lambda d: f"[{d['function']}] {d['title']} ({d['kind']}) — due {d['due']}, "
        + (f"{d['days_left']} day(s) left" if d["days_left"] >= 0 else f"{-d['days_left']} day(s) past due"),
    )
    section(
        "Decisions waiting on the owner",
        snapshot["decisions"],
        lambda d: f"{d['question']} — waiting {d['waiting_days']} day(s)",
    )
    section(
        "Metrics",
        snapshot["metrics"],
        lambda m: f"[{m['function']}] {m['name']}: "
        + (
            f"{m['latest_value']:g} {m['unit']} for period starting {m['latest_period']}"
            if m["latest_value"] is not None
            else "never reported"
        )
        + (f", target {m['target']:g}" if m["target"] is not None else ", no target set")
        + (" — latest period missing" if m["missing"] and m["latest_value"] is not None else "")
        + (" — OFF TARGET" if m["on_target"] is False else ""),
    )

    lines.extend(["", "## Gaps in the board itself", ""])
    lines.append(
        "- Functions with no owner: " + (", ".join(gaps["functions_without_owner"]) or "none")
    )
    lines.append(
        "- Metrics with no target: " + (", ".join(gaps["metrics_without_target"]) or "none")
    )
    if gaps["no_deadlines_entered"]:
        lines.append("- No deadlines have been entered yet, so none can be watched.")
    return "\n".join(lines) + "\n"
