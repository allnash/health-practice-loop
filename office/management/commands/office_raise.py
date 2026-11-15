"""Let the loop put a task or a decision on the board.

    manage.py office_raise task --function billing-insurance --title "..." \\
        [--details "..."] [--due 2026-11-20] [--priority high]
    manage.py office_raise decision --question "..." [--function finance-reporting] \\
        [--context "..."] [--recommendation "..."]

Raising the same open item twice does nothing, so a repeated run cannot pile up
duplicates.
"""

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from office.models import Decision, Function, Task


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        kinds = parser.add_subparsers(dest="what", required=True)

        task = kinds.add_parser("task")
        task.add_argument("--function", required=True, help="Function slug.")
        task.add_argument("--title", required=True)
        task.add_argument("--details", default="")
        task.add_argument("--due", type=date.fromisoformat)
        task.add_argument("--priority", choices=[p.name.lower() for p in Task.Priority], default="normal")

        decision = kinds.add_parser("decision")
        decision.add_argument("--question", required=True)
        decision.add_argument("--function", help="Function slug.")
        decision.add_argument("--context", default="")
        decision.add_argument("--recommendation", default="")

    def _function(self, slug):
        if not slug:
            return None
        try:
            return Function.objects.get(slug=slug)
        except Function.DoesNotExist:
            known = ", ".join(Function.objects.values_list("slug", flat=True))
            raise CommandError(f"No function with slug “{slug}”. Known: {known}") from None

    def handle(self, *args, **options):
        function = self._function(options.get("function"))

        if options["what"] == "task":
            existing = Task.objects.filter(function=function, title=options["title"]).exclude(
                status=Task.Status.DONE
            )
            if existing.exists():
                self.stdout.write(f"Already open: task #{existing.first().pk}")
                return
            task = Task.objects.create(
                function=function,
                title=options["title"],
                details=options["details"],
                due_date=options["due"],
                priority=Task.Priority[options["priority"].upper()],
                raised_by_loop=True,
            )
            self.stdout.write(self.style.SUCCESS(f"Raised task #{task.pk}"))
            return

        existing = Decision.objects.filter(question=options["question"], status=Decision.Status.OPEN)
        if existing.exists():
            self.stdout.write(f"Already open: decision #{existing.first().pk}")
            return
        decision = Decision.objects.create(
            function=function,
            question=options["question"],
            context=options["context"],
            recommendation=options["recommendation"],
            raised_by_loop=True,
        )
        self.stdout.write(self.style.SUCCESS(f"Raised decision #{decision.pk}"))
