from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import Deadline, Decision, Function, LoopRun, Metric, MetricEntry, Routine, Task, add_months
from .dashboard import render_summary
from .services import build_snapshot, render_brief, workload

SUNDAY = date(2026, 11, 15)
MONDAY = date(2026, 11, 16)


class ScheduleTests(TestCase):
    def setUp(self):
        self.function = Function.objects.create(name="Billing", slug="billing")

    def routine(self, cadence, next_due):
        return Routine.objects.create(function=self.function, title="r", cadence=cadence, next_due=next_due)

    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2026, 11, 30), 3), date(2027, 2, 28))

    def test_daily_routine_skips_the_weekend(self):
        routine = self.routine("daily", date(2026, 11, 13))  # a Friday
        routine.mark_done(date(2026, 11, 13))
        self.assertEqual(routine.next_due, MONDAY)

    def test_weekly_routine_keeps_its_weekday_when_done_late(self):
        routine = self.routine("weekly", date(2026, 10, 30))  # a Friday, two weeks late
        routine.mark_done(MONDAY)
        self.assertEqual(routine.next_due, date(2026, 11, 20))
        self.assertEqual(routine.last_done, MONDAY)

    def test_routine_done_early_moves_past_the_occurrence_it_covered(self):
        routine = self.routine("weekly", date(2026, 11, 20))
        routine.mark_done(date(2026, 11, 19))
        self.assertEqual(routine.next_due, date(2026, 11, 27))

    def test_recurring_deadline_rolls_forward_and_one_off_closes(self):
        recurring = Deadline.objects.create(
            function=self.function, title="License", due_date=date(2026, 12, 1), recurs_every_months=24
        )
        recurring.mark_done(MONDAY)
        self.assertEqual(recurring.due_date, date(2028, 12, 1))
        self.assertFalse(recurring.is_closed)

        one_off = Deadline.objects.create(function=self.function, title="Lease", due_date=date(2026, 12, 1))
        one_off.mark_done(MONDAY)
        self.assertTrue(one_off.is_closed)


class SnapshotTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("pat", first_name="Pat", last_name="Lee")
        self.billing = Function.objects.create(name="Billing", slug="billing", owner=self.owner)
        self.intake = Function.objects.create(name="Intake", slug="intake")

    def test_counts_what_is_due_late_and_missing(self):
        Routine.objects.create(function=self.billing, title="Due today", cadence="daily", next_due=MONDAY)
        Routine.objects.create(function=self.billing, title="Late", cadence="weekly", next_due=date(2026, 11, 12))
        Routine.objects.create(function=self.intake, title="Later", cadence="weekly", next_due=date(2026, 11, 20))
        Task.objects.create(function=self.intake, title="Late task", due_date=date(2026, 11, 10))
        Task.objects.create(function=self.intake, title="Finished", status=Task.Status.DONE)
        Deadline.objects.create(function=self.billing, title="Soon", due_date=date(2026, 12, 1), lead_days=30)
        Deadline.objects.create(function=self.billing, title="Far", due_date=date(2027, 6, 1), lead_days=30)
        Decision.objects.create(function=self.intake, question="Hire a second front desk person?")
        reported = Metric.objects.create(
            function=self.billing, name="Denial rate", unit="%", direction="lower", target=Decimal("5")
        )
        MetricEntry.objects.create(metric=reported, period_start=date(2026, 11, 9), value=Decimal("8"))
        Metric.objects.create(function=self.intake, name="Inquiries")

        snapshot = build_snapshot(MONDAY)

        self.assertEqual(
            snapshot["totals"],
            {
                "routines_due_today": 1,
                "routines_overdue": 1,
                "tasks_open": 1,
                "tasks_overdue": 1,
                "deadlines_flagged": 1,
                "deadlines_overdue": 0,
                "decisions_open": 1,
                "metrics_missing": 1,
                "metrics_off_target": 1,
            },
        )
        by_name = {row["name"]: row for row in snapshot["functions"]}
        self.assertEqual(by_name["Billing"]["status"], "attention")
        self.assertEqual(by_name["Billing"]["owner"], "Pat Lee")
        self.assertEqual(by_name["Intake"]["status"], "attention")
        self.assertEqual(snapshot["gaps"]["functions_without_owner"], ["Intake"])
        self.assertEqual(snapshot["gaps"]["metrics_never_reported"], ["Inquiries"])
        self.assertIn("Denial rate: 8 % for period starting 2026-11-09, target 5 — OFF TARGET", render_brief(snapshot))

    def test_last_weeks_number_is_expected_only_once_the_week_has_ended(self):
        metric = Metric.objects.create(function=self.billing, name="Claims")
        self.assertEqual(metric.latest_complete_period_start(SUNDAY), date(2026, 11, 2))
        self.assertEqual(metric.latest_complete_period_start(MONDAY), date(2026, 11, 9))

    def test_workload_projects_routines_and_counts_late_work_today(self):
        Routine.objects.create(function=self.billing, title="Daily", cadence="daily", next_due=MONDAY)
        Routine.objects.create(function=self.billing, title="Late", cadence="monthly", next_due=date(2026, 11, 10))
        Task.objects.create(function=self.intake, title="Late task", due_date=date(2026, 11, 10))
        Deadline.objects.create(function=self.billing, title="Soon", due_date=date(2026, 11, 18))

        result = workload(MONDAY, days=7)  # Monday through Sunday

        self.assertEqual(result["labels"][0], "Mon 16")
        self.assertEqual(result["routines"], [2, 1, 1, 1, 1, 0, 0])
        self.assertEqual(result["tasks"], [1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(result["deadlines"], [0, 0, 1, 0, 0, 0, 0])

    def test_quiet_function_is_on_track(self):
        snapshot = build_snapshot(MONDAY)
        self.assertEqual({row["status"] for row in snapshot["functions"]}, {"ok"})
        self.assertTrue(snapshot["gaps"]["no_deadlines_entered"])


class CommandTests(TestCase):
    def test_seed_is_repeatable(self):
        call_command("seed_office", stdout=StringIO())
        counts = (Function.objects.count(), Routine.objects.count(), Metric.objects.count(), Task.objects.count())
        self.assertEqual(counts[0], 10)
        call_command("seed_office", stdout=StringIO())
        self.assertEqual(
            counts, (Function.objects.count(), Routine.objects.count(), Metric.objects.count(), Task.objects.count())
        )
        self.assertFalse(MetricEntry.objects.exists())
        self.assertFalse(Metric.objects.exclude(target=None).exists())

    def test_loop_reads_without_writing_and_records_on_request(self):
        call_command("seed_office", stdout=StringIO())
        out = StringIO()
        call_command("office_loop", stdout=out)
        self.assertIn("## By function", out.getvalue())
        self.assertFalse(LoopRun.objects.exists())

        call_command(
            "office_loop", "--record", "--kind", "full", "--focus", "Get the board set up",
            "--summary", "Six setup tasks are open.", "--next-checkpoint", "2026-11-23", stdout=StringIO(),
        )
        run = LoopRun.objects.get()
        self.assertEqual(run.kind, "full")
        self.assertEqual(run.next_checkpoint, date(2026, 11, 23))
        self.assertEqual(run.snapshot["totals"]["tasks_open"], 6)

    def test_raising_the_same_open_item_twice_adds_one(self):
        Function.objects.create(name="Billing", slug="billing")
        for _ in range(2):
            call_command("office_raise", "task", "--function", "billing", "--title", "Call the payer", stdout=StringIO())
            call_command("office_raise", "decision", "--question", "Change clearinghouse?", stdout=StringIO())
        self.assertEqual(Task.objects.filter(raised_by_loop=True).count(), 1)
        self.assertEqual(Decision.objects.filter(raised_by_loop=True).count(), 1)


class AdminTests(TestCase):
    def setUp(self):
        call_command("seed_office", stdout=StringIO())
        self.client.force_login(User.objects.create_superuser("boss", password="x"))

    def test_dashboard_is_the_home_page(self):
        LoopRun.objects.create(kind="full", focus="Get the board set up", summary="Six setup tasks are open.")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for text in ["Routines due", "Front desk &amp; scheduling", "Decisions waiting on you", "Get the board set up"]:
            self.assertContains(response, text)

    def test_summary_keeps_bold_and_bullets_and_escapes_the_rest(self):
        html = render_summary("**Status**\n- One <b>late</b> task\n- Two due\n\nNext review Monday.")
        self.assertEqual(
            html,
            '<p class="mb-1"><strong>Status</strong></p>'
            '<ul class="pl-5 mb-2" style="list-style: disc"><li>One &lt;b&gt;late&lt;/b&gt; task</li><li>Two due</li></ul>'
            '<p class="mb-1">Next review Monday.</p>',
        )

    def test_metric_page_charts_its_trend_once_there_are_two_values(self):
        metric = Metric.objects.first()
        url = reverse("admin:office_metric_change", args=[metric.pk])
        self.assertNotContains(self.client.get(url), "data-type=\"line\"")
        MetricEntry.objects.create(metric=metric, period_start=date(2026, 11, 2), value=40)
        MetricEntry.objects.create(metric=metric, period_start=date(2026, 11, 9), value=44)
        response = self.client.get(url)
        self.assertContains(response, "data-type=\"line\"")
        self.assertContains(response, "Nov 02")

    def test_every_screen_opens(self):
        for model in ["function", "routine", "task", "deadline", "metric", "metricentry", "decision", "looprun"]:
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(f"admin:office_{model}_changelist")).status_code, 200)
                self.assertEqual(self.client.get(reverse(f"admin:office_{model}_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:auth_user_changelist")).status_code, 200)
        function = Function.objects.first()
        self.assertEqual(self.client.get(reverse("admin:office_function_change", args=[function.pk])).status_code, 200)

    def test_done_button_moves_a_routine_forward(self):
        routine = Routine.objects.filter(cadence="daily").first()
        before = routine.next_due
        response = self.client.get(reverse("admin:office_routine_mark_done_row", args=[routine.pk]))
        self.assertEqual(response.status_code, 302)
        routine.refresh_from_db()
        self.assertGreater(routine.next_due, before)
        self.assertIsNotNone(routine.last_done)
