# Office Manager loop

The plan for this practice's Business Loop. The method is
[`playbooks/product/business-loop.md`](../playbooks/product/business-loop.md);
this file is its application here. Schedule and delivery state are in
[`routines.json`](../routines.json). Each run's report is in [`reports/`](../reports/).

## What the founder asked for

In their words, 2026-11-15:

- "how do I use egbe.ai to crate a loop for a Mental Health practice"
- "set it up as a dashboard in django, we will only use django admin to drive this using
  https://unfoldadmin.com/"
- "set up and Office manager loop that manages all the functions"
- "Please use egbe for loops"
- "do it all", in reply to three recommendations: put new-client flow first, keep the loop
  running when Claude Code is closed, and leave Egbe session logging off.

## Working understanding

- **Business:** a mental health practice. Whether it is already operating and its size have not
  been stated. *Assumption until told otherwise:* an existing outpatient practice with a front
  office.
- **Outcome wanted:** every function of the office keeps running without the founder having to
  chase it: recurring duties get done, dated obligations are not missed, the weekly numbers are
  visible, and choices that are the founder's reach them with a recommendation.
- **First priority:** new-client flow, measured by new client inquiries, intakes booked and days
  from inquiry to first appointment. When several things compete, work that protects or improves
  these comes first. Missed-deadline risk (licenses, credentialing, insurance) still outranks it.

## The cycle

| Part | Here |
|---|---|
| Signal | The office board in the Django admin: routines due and late, open tasks, deadlines inside their warning window, weekly metrics against targets, decisions waiting |
| Work I do | Read the board, find what is late, missing or drifting, raise tasks and decisions, write the review, and prepare what I am asked to prepare |
| Feedback | What people mark done, the numbers they enter, and the founder's answers to decisions |
| Checkpoint | A full review each Monday; a short check on other weekdays that stays quiet unless something material changed |

## What a run may and may not do

May, without asking:

- Read the board and the project's `egbe-docs/`.
- Record the run, and raise tasks and decisions on the board (marked as raised by the loop).
- Write the run's report under `egbe-docs/reports/` and update `egbe-docs/routines.json`.

Needs the founder's agreement first:

- Marking routines, tasks or deadlines done. People do the work, so people mark it.
- Changing owners, routines, targets or deadlines.
- Any spending, outreach, email, publishing or advertising, including through Egbe.
- Changing this loop's schedule, or any code in this project.

Never:

- Client names, clinical details or anything else that identifies a client, on the board, in
  reports or in anything sent to Egbe. The board holds counts and office work only.

## How a scheduled run goes

A scheduled run is unattended: nobody can answer a question or approve anything. Use
`./bin/office` for every board command; it is the only command the run is allowed besides `date`.

1. Read this file, the method, `egbe-docs/routines.json` and the newest `summary.md` under
   `egbe-docs/reports/`. If `routines.json` has `enabled: false` for business 2947, stop and
   print "Loop is disabled."
2. Read the board: `./bin/office office_loop`.
3. Decide the kind of run. Monday is a full review. Any other day is a brief check.
4. For a brief check, compare the board with the previous run's `snapshot.json`. Something
   material changed if work became late, a deadline entered its warning window, a metric went
   off target or is newly missing, the founder answered a decision, or a setup task was finished.
   If nothing material changed, write no report and record no run: set `last_completed` in
   `routines.json` to today's occurrence with result "no material change", print one line saying
   so, and stop.
5. Otherwise write the run's files under `egbe-docs/reports/<id>-<brief|detailed>/`, where `<id>`
   is `date -u +%Y-%m-%dT%H%M%SZ`:
   - `snapshot.json`: the output of `./bin/office office_loop --json`, wrapped as the first
     report's snapshot is.
   - `summary.md`: short bold headings and one-line bullets. Status, what needs attention, the
     focus, and decisions waiting on the founder. This is what the dashboard shows.
   - `report.md`, on Mondays only: the full review, in the shape of the first report.
6. Put anything new on the board with `./bin/office office_raise task ...` or
   `./bin/office office_raise decision ...`. Raise a decision only for a choice that is the
   founder's. Do not raise an item that is already open.
7. Record the run so the dashboard shows it:
   `./bin/office office_loop --record --kind <brief|full> --focus "..." --summary-file <summary.md> --next-checkpoint <next Monday> --report-path <path>`.
8. Update `last_completed` and `last_delivered` for business 2947 in `routines.json`. The
   dashboard is the delivery destination, so a recorded run counts as delivered.
9. Finish with the summary text.

## State

- 2026-11-15: board created with ten functions, a starter set of routines and metric
  definitions, and six setup tasks. First review run by hand the same day.
- 2026-11-15: the founder chose new-client flow as the first priority, asked for the loop to keep
  running when Claude Code is closed, and declined Egbe session logging
  (`egbe-docs/telemetry/setup.json`).
- Scheduling is recorded in `routines.json`. Check the actual job there before assuming it runs.
