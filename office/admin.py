import json

from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, User
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import (
    ChoicesDropdownFilter,
    RangeDateFilter,
    RelatedDropdownFilter,
)
from unfold.decorators import action, display
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import Deadline, Decision, Function, LoopRun, Metric, MetricEntry, Routine, Task
from .services import build_snapshot

admin.site.index_title = "Office dashboard"

admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


class MarkDoneMixin:
    """A "Done" button on every row plus the same thing as a bulk action."""

    actions = ["mark_done"]
    actions_row = ["mark_done_row"]

    def _complete(self, obj):
        raise NotImplementedError

    @admin.action(description="Mark selected as done")
    def mark_done(self, request, queryset):
        count = 0
        for obj in queryset:
            self._complete(obj)
            count += 1
        self.message_user(request, f"Marked {count} done.", messages.SUCCESS)

    @action(description="Done", url_path="mark-done", permissions=["change"])
    def mark_done_row(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is not None:
            self._complete(obj)
            self.message_user(request, f"“{obj}” marked done.", messages.SUCCESS)
        opts = self.model._meta
        return redirect(
            request.META.get("HTTP_REFERER")
            or reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        )


class RoutineInline(TabularInline):
    model = Routine
    fields = ["title", "cadence", "owner", "next_due", "is_active"]
    extra = 0
    show_change_link = True


class MetricInline(TabularInline):
    model = Metric
    fields = ["name", "unit", "period", "direction", "target", "is_active"]
    extra = 0
    show_change_link = True


@admin.register(Function)
class FunctionAdmin(ModelAdmin):
    list_display = ["name", "owner", "open_work", "order", "is_active"]
    list_editable = ["order"]
    search_fields = ["name", "description"]
    prepopulated_fields = {"slug": ["name"]}
    autocomplete_fields = ["owner"]
    inlines = [RoutineInline, MetricInline]
    change_form_before_template = "office/function_summary.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        rows = {str(row["id"]): row for row in build_snapshot()["functions"]}
        extra_context = {**(extra_context or {}), "office_function": rows.get(str(object_id))}
        return super().change_view(request, object_id, form_url, extra_context)

    @display(description="Routines · open tasks · deadlines")
    def open_work(self, obj):
        tasks = obj.tasks.exclude(status=Task.Status.DONE).count()
        return (
            f"{obj.routines.filter(is_active=True).count()} · {tasks} · "
            f"{obj.deadlines.filter(is_closed=False).count()}"
        )


@admin.register(Routine)
class RoutineAdmin(MarkDoneMixin, ModelAdmin):
    list_display = ["title", "function", "cadence", "responsible_name", "next_due", "state", "last_done"]
    list_filter = [
        ("function", RelatedDropdownFilter),
        ("cadence", ChoicesDropdownFilter),
        ("next_due", RangeDateFilter),
        "is_active",
    ]
    list_filter_submit = True
    search_fields = ["title", "instructions"]
    autocomplete_fields = ["function", "owner"]
    date_hierarchy = "next_due"

    def _complete(self, obj):
        obj.mark_done()

    @display(description="Responsible")
    def responsible_name(self, obj):
        person = obj.responsible
        return (person.get_full_name() or person.get_username()) if person else "Unassigned"

    @display(description="State", label={"Overdue": "danger", "Due today": "warning", "Upcoming": "success", "Paused": "info"})
    def state(self, obj):
        if not obj.is_active:
            return "Paused"
        today = timezone.localdate()
        if obj.next_due < today:
            return "Overdue"
        return "Due today" if obj.next_due == today else "Upcoming"


@admin.register(Task)
class TaskAdmin(MarkDoneMixin, ModelAdmin):
    list_display = ["title", "function", "status_label", "priority_label", "owner", "due_date", "raised_by_loop"]
    list_filter = [
        ("function", RelatedDropdownFilter),
        ("status", ChoicesDropdownFilter),
        ("priority", ChoicesDropdownFilter),
        ("owner", RelatedDropdownFilter),
        ("due_date", RangeDateFilter),
        "raised_by_loop",
    ]
    list_filter_submit = True
    search_fields = ["title", "details"]
    autocomplete_fields = ["function", "owner"]
    readonly_fields = ["completed_at", "created_at", "updated_at"]
    date_hierarchy = "due_date"

    def _complete(self, obj):
        obj.status = Task.Status.DONE
        obj.save()

    @display(description="Status", ordering="status", label={"To do": "info", "In progress": "warning", "Blocked": "danger", "Done": "success"})
    def status_label(self, obj):
        return obj.get_status_display()

    @display(description="Priority", ordering="priority", label={"Urgent": "danger", "High": "warning", "Normal": "info"})
    def priority_label(self, obj):
        return obj.get_priority_display()


@admin.register(Deadline)
class DeadlineAdmin(MarkDoneMixin, ModelAdmin):
    list_display = ["title", "function", "kind", "owner", "due_date", "state", "recurs_every_months"]
    list_filter = [
        ("function", RelatedDropdownFilter),
        ("kind", ChoicesDropdownFilter),
        ("due_date", RangeDateFilter),
        "is_closed",
    ]
    list_filter_submit = True
    search_fields = ["title", "notes"]
    autocomplete_fields = ["function", "owner"]
    readonly_fields = ["last_completed_on"]
    date_hierarchy = "due_date"

    def _complete(self, obj):
        obj.mark_done()

    @display(description="State", label={"Past due": "danger", "Coming up": "warning", "Scheduled": "success", "Closed": "info"})
    def state(self, obj):
        if obj.is_closed:
            return "Closed"
        today = timezone.localdate()
        if obj.due_date < today:
            return "Past due"
        return "Coming up" if obj.flag_from <= today else "Scheduled"


class MetricEntryInline(TabularInline):
    model = MetricEntry
    fields = ["period_start", "value", "note"]
    extra = 1


@admin.register(Metric)
class MetricAdmin(ModelAdmin):
    list_display = ["name", "function", "period", "latest", "target", "direction", "is_active"]
    list_filter = [("function", RelatedDropdownFilter), ("period", ChoicesDropdownFilter), "is_active"]
    list_filter_submit = True
    search_fields = ["name", "description"]
    autocomplete_fields = ["function"]
    inlines = [MetricEntryInline]
    change_form_before_template = "office/metric_chart.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        metric = self.get_object(request, object_id)
        entries = list(metric.entries.all()[:12])[::-1] if metric else []
        chart = None
        if len(entries) > 1:
            datasets = [
                {
                    "label": f"{metric.name} ({metric.unit})" if metric.unit else metric.name,
                    "data": [float(entry.value) for entry in entries],
                    "borderColor": "var(--color-primary-600)",
                }
            ]
            if metric.target is not None:
                datasets.append(
                    {
                        "label": "Target",
                        "data": [float(metric.target)] * len(entries),
                        "borderColor": "var(--color-base-400)",
                        "borderDash": [6, 6],
                    }
                )
            chart = json.dumps(
                {"labels": [entry.period_start.strftime("%b %d") for entry in entries], "datasets": datasets}
            )
        extra_context = {**(extra_context or {}), "office_metric_chart": chart}
        return super().change_view(request, object_id, form_url, extra_context)

    @display(description="Latest value")
    def latest(self, obj):
        entry = obj.entries.first()
        if entry is None:
            return "Not reported yet"
        return f"{entry.value:g} {obj.unit} ({entry.period_start:%b %d})"


@admin.register(MetricEntry)
class MetricEntryAdmin(ModelAdmin):
    list_display = ["metric", "period_start", "value", "note"]
    list_filter = [("metric", RelatedDropdownFilter), ("period_start", RangeDateFilter)]
    list_filter_submit = True
    autocomplete_fields = ["metric"]
    date_hierarchy = "period_start"


@admin.register(Decision)
class DecisionAdmin(ModelAdmin):
    list_display = ["question", "function", "status_label", "created_at", "decided_on", "raised_by_loop"]
    list_filter = [("status", ChoicesDropdownFilter), ("function", RelatedDropdownFilter), "raised_by_loop"]
    list_filter_submit = True
    search_fields = ["question", "context", "answer"]
    autocomplete_fields = ["function"]
    readonly_fields = ["created_at"]

    @display(description="Status", ordering="status", label={"Waiting on you": "warning", "Decided": "success", "Dropped": "info"})
    def status_label(self, obj):
        return obj.get_status_display()


@admin.register(LoopRun)
class LoopRunAdmin(ModelAdmin):
    list_display = ["started_at", "kind", "focus", "next_checkpoint"]
    list_filter = [("kind", ChoicesDropdownFilter), ("started_at", RangeDateFilter)]
    list_filter_submit = True
    search_fields = ["focus", "summary"]
    date_hierarchy = "started_at"
