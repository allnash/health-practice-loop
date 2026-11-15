Read and apply EGBE.md when working on this project.

## This project

A Django admin dashboard (django-unfold) for running a mental health practice's office, plus an
Egbe Business Loop that reviews it. The admin is the whole app and is served at `/`.

- Pipenv is installed under pyenv 3.12.13; the project itself runs on Python 3.13. Prefix
  commands with `PYENV_VERSION=3.12.13`, for example
  `PYENV_VERSION=3.12.13 pipenv run python manage.py runserver`.
- Tests: `PYENV_VERSION=3.12.13 pipenv run python manage.py test office`.
- Starter content: `manage.py seed_office` (safe to rerun).
- The loop reads the board with `manage.py office_loop`, records a run with `office_loop --record`
  and raises tasks or decisions with `manage.py office_raise`. Its plan and limits are in
  `egbe-docs/product/office-manager-loop.md`.
- The board holds office work and counts only. Never add client names, clinical details or a
  client model.
