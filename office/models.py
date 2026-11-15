"""Operational records for running a practice office.

Everything here is about the business of the office: recurring duties, tasks,
dated obligations, weekly numbers and decisions. It deliberately has no client
model. Keep client names and clinical details in the practice's EHR, not here.
"""

import calendar
from datetime import date, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

NO_CLIENT_INFO = "Operational notes only. No client names or clinical details."


def add_months(day: date, months: int) -> date:
    """Same day-of-month `months` later, clamped to the end of shorter months."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def next_weekday(day: date) -> date:
    following = day + timedelta(days=1)
    while following.weekday() >= 5:
        following += timedelta(days=1)
    return following


class Function(models.Model):
    """An area of responsibility the office manager keeps running."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_functions",
        help_text="Who answers for this area day to day.",
    )
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Routine(models.Model):
    """A recurring duty. Marking it done moves it to its next occurrence."""

    class Cadence(models.TextChoices):
        DAILY = "daily", "Every weekday"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        YEARLY = "yearly", "Yearly"

    function = models.ForeignKey(Function, on_delete=models.CASCADE, related_name="routines")
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True, help_text=NO_CLIENT_INFO)
    cadence = models.CharField(max_length=12, choices=Cadence.choices, default=Cadence.WEEKLY)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="routines",
        help_text="Leave empty to use the function's owner.",
    )
    next_due = models.DateField(default=timezone.localdate)
    last_done = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["next_due", "function__order", "title"]

    def __str__(self):
        return self.title

    def _step(self, day: date) -> date:
        if self.cadence == self.Cadence.DAILY:
            return next_weekday(day)
        if self.cadence == self.Cadence.WEEKLY:
            return day + timedelta(days=7)
        months = {self.Cadence.MONTHLY: 1, self.Cadence.QUARTERLY: 3, self.Cadence.YEARLY: 12}
        return add_months(day, months[self.cadence])

    def mark_done(self, done_on: date | None = None) -> None:
        """Record completion and move to the first occurrence after `done_on`.

        The schedule keeps its anchor (a Friday routine stays on Fridays), and a
        routine that was several periods late does not come due again at once.
        """
        done_on = done_on or timezone.localdate()
        following = self._step(self.next_due)
        while following <= done_on:
            following = self._step(following)
        self.last_done = done_on
        self.next_due = following
        self.save(update_fields=["last_done", "next_due"])

    @property
    def responsible(self):
        return self.owner or self.function.owner


class Task(models.Model):
    """A one-off piece of work."""

    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"

    class Priority(models.IntegerChoices):
        LOW = 1, "Low"
        NORMAL = 2, "Normal"
        HIGH = 3, "High"
        URGENT = 4, "Urgent"

    function = models.ForeignKey(Function, on_delete=models.CASCADE, related_name="tasks")
    title = models.CharField(max_length=160)
    details = models.TextField(blank=True, help_text=NO_CLIENT_INFO)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TODO)
    priority = models.PositiveSmallIntegerField(choices=Priority.choices, default=Priority.NORMAL)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    due_date = models.DateField(null=True, blank=True)
    raised_by_loop = models.BooleanField(
        default=False, help_text="Created by the Office Manager loop rather than a person."
    )
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-priority", "due_date", "id"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.status == self.Status.DONE and self.completed_at is None:
            self.completed_at = timezone.now()
        elif self.status != self.Status.DONE:
            self.completed_at = None
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status != self.Status.DONE


class Deadline(models.Model):
    """A dated obligation that costs something if it is missed."""

    class Kind(models.TextChoices):
        LICENSE = "license", "Clinician license"
        CREDENTIALING = "credentialing", "Payer credentialing"
        INSURANCE = "insurance", "Insurance policy"
        CONTRACT = "contract", "Contract or lease"
        COMPLIANCE = "compliance", "Compliance"
        FILING = "filing", "Tax or government filing"
        OTHER = "other", "Other"

    function = models.ForeignKey(Function, on_delete=models.CASCADE, related_name="deadlines")
    title = models.CharField(max_length=160)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.OTHER)
    due_date = models.DateField()
    lead_days = models.PositiveSmallIntegerField(
        default=60, help_text="Start flagging this many days before it is due."
    )
    recurs_every_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="If set, completing it moves the due date forward instead of closing it.",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deadlines",
    )
    notes = models.TextField(blank=True, help_text=NO_CLIENT_INFO)
    last_completed_on = models.DateField(null=True, blank=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["is_closed", "due_date"]

    def __str__(self):
        return self.title

    def mark_done(self, done_on: date | None = None) -> None:
        done_on = done_on or timezone.localdate()
        self.last_completed_on = done_on
        if self.recurs_every_months:
            following = add_months(self.due_date, self.recurs_every_months)
            while following <= done_on:
                following = add_months(following, self.recurs_every_months)
            self.due_date = following
        else:
            self.is_closed = True
        self.save(update_fields=["last_completed_on", "due_date", "is_closed"])

    @property
    def flag_from(self) -> date:
        return self.due_date - timedelta(days=self.lead_days)


class Metric(models.Model):
    """A number the office reports each period. Aggregates only."""

    class Period(models.TextChoices):
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    class Direction(models.TextChoices):
        HIGHER = "higher", "Higher is better"
        LOWER = "lower", "Lower is better"

    function = models.ForeignKey(Function, on_delete=models.CASCADE, related_name="metrics")
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=24, blank=True, help_text="For example: count, %, days, $.")
    description = models.TextField(blank=True)
    period = models.CharField(max_length=8, choices=Period.choices, default=Period.WEEKLY)
    direction = models.CharField(max_length=8, choices=Direction.choices, default=Direction.HIGHER)
    target = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["function__order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["function", "name"], name="unique_metric_per_function")
        ]

    def __str__(self):
        return self.name

    def latest_complete_period_start(self, today: date | None = None) -> date:
        """Start of the most recent period that has fully ended."""
        today = today or timezone.localdate()
        if self.period == self.Period.WEEKLY:
            this_monday = today - timedelta(days=today.weekday())
            return this_monday - timedelta(days=7)
        return add_months(today.replace(day=1), -1)

    def meets_target(self, value) -> bool | None:
        if self.target is None or value is None:
            return None
        if self.direction == self.Direction.HIGHER:
            return value >= self.target
        return value <= self.target


class MetricEntry(models.Model):
    metric = models.ForeignKey(Metric, on_delete=models.CASCADE, related_name="entries")
    period_start = models.DateField(
        help_text="Monday of the week, or the first day of the month, that this value covers."
    )
    value = models.DecimalField(max_digits=12, decimal_places=2)
    note = models.CharField(max_length=240, blank=True, help_text=NO_CLIENT_INFO)

    class Meta:
        ordering = ["-period_start"]
        verbose_name_plural = "metric entries"
        constraints = [
            models.UniqueConstraint(fields=["metric", "period_start"], name="one_entry_per_period")
        ]

    def __str__(self):
        return f"{self.metric} · {self.period_start:%b %d, %Y}"


class Decision(models.Model):
    """A choice that belongs to the practice owner, with what it is waiting on."""

    class Status(models.TextChoices):
        OPEN = "open", "Waiting on you"
        DECIDED = "decided", "Decided"
        DROPPED = "dropped", "Dropped"

    function = models.ForeignKey(
        Function, null=True, blank=True, on_delete=models.SET_NULL, related_name="decisions"
    )
    question = models.CharField(max_length=240)
    context = models.TextField(blank=True, help_text=NO_CLIENT_INFO)
    recommendation = models.TextField(blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    answer = models.TextField(blank=True)
    decided_on = models.DateField(null=True, blank=True)
    raised_by_loop = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["status", "-created_at"]

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        if self.status == self.Status.OPEN:
            self.decided_on = None
        elif self.decided_on is None:
            self.decided_on = timezone.localdate()
        super().save(*args, **kwargs)


class LoopRun(models.Model):
    """One pass of the Office Manager loop and what it concluded."""

    class Kind(models.TextChoices):
        BRIEF = "brief", "Brief check"
        FULL = "full", "Full review"

    started_at = models.DateTimeField(default=timezone.now)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.BRIEF)
    focus = models.CharField(max_length=240, blank=True, help_text="The one thing that matters most now.")
    summary = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    next_checkpoint = models.DateField(null=True, blank=True)
    report_path = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {timezone.localtime(self.started_at):%b %d, %Y %H:%M}"
