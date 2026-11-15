"""Read the office's current state, and record what a loop run concluded.

    manage.py office_loop                 print the state as a Markdown brief
    manage.py office_loop --json          print the same state as JSON
    manage.py office_loop --record --kind full --focus "..." \\
        --summary-file summary.md --next-checkpoint 2026-11-23
                                          save a loop run so the dashboard shows it

Reading changes nothing. Recording adds one LoopRun row.
"""

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from office.models import LoopRun
from office.services import build_snapshot, render_brief


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print the snapshot as JSON.")
        parser.add_argument("--record", action="store_true", help="Save this run as a LoopRun.")
        parser.add_argument("--kind", choices=LoopRun.Kind.values, default=LoopRun.Kind.BRIEF)
        parser.add_argument("--focus", default="")
        parser.add_argument("--summary", default="")
        parser.add_argument("--summary-file", type=Path)
        parser.add_argument("--next-checkpoint", type=date.fromisoformat)
        parser.add_argument("--report-path", default="")

    def handle(self, *args, **options):
        snapshot = build_snapshot()

        if not options["record"]:
            self.stdout.write(json.dumps(snapshot, indent=2) if options["json"] else render_brief(snapshot))
            return

        summary = options["summary"]
        if options["summary_file"]:
            try:
                summary = options["summary_file"].read_text()
            except OSError as error:
                raise CommandError(f"Could not read the summary file: {error}") from error
        if not summary.strip():
            raise CommandError("A recorded run needs --summary or --summary-file.")

        run = LoopRun.objects.create(
            kind=options["kind"],
            focus=options["focus"],
            summary=summary.strip(),
            snapshot=snapshot,
            next_checkpoint=options["next_checkpoint"],
            report_path=options["report_path"],
        )
        self.stdout.write(self.style.SUCCESS(f"Recorded loop run #{run.pk}: {run}"))
