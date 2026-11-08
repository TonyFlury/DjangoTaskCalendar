# Build the package

Run these commands from the repository root, where `pyproject.toml` is located.
Python 3.12 or later is required. Building the distributions does not require a
Django host project, database connection, migrations, or `collectstatic`.

## Prepare the build environment

Create a separate environment for packaging tools:

```bash
python3.12 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip build twine
```

On Windows, activate the environment with `.venv-build\Scripts\activate`.
For later builds, activate the existing environment and reuse it.
Internet access is required to download tools and isolated build dependencies.

## Build

Check the `[project]` version in `pyproject.toml` before building a new release.
The distribution name is `django-task-calendar`; the Python import name is `Diary`.

```bash
python -m build
```

This creates a source distribution, then builds a wheel from that source
distribution. The default output directory is `dist/`.
For version `0.1.5.1`, the output files are:

```text
dist/django_task_calendar-0.1.5.1.tar.gz
dist/django_task_calendar-0.1.5.1-py3-none-any.whl
```

The build uses the setuptools backend and dependency requirements declared in
`pyproject.toml`. Build isolation installs those dependencies in a temporary
environment; they do not need to be installed manually in the build environment.

To keep a build separate from existing artifacts, choose an empty output directory:

```bash
python -m build --outdir dist/review
```

## Check the distributions

Check the metadata and README rendering for the files from this build:

```bash
python -m twine check --strict dist/django_task_calendar-0.1.5.1.tar.gz dist/django_task_calendar-0.1.5.1-py3-none-any.whl
```

Replace the version and directory in these commands when they differ from your
build. Use the exact artifact names so older files in `dist/` are not selected.

Inspect the wheel contents:

```bash
python -m zipfile -l dist/django_task_calendar-0.1.5.1-py3-none-any.whl
```

The wheel must contain the `Diary` modules, management commands, migrations,
HTML templates, CSS, and JavaScript. `Diary.tests` is excluded from the wheel.

## Install the wheel in a host project

Activate the host project's environment, then install the built wheel using its
absolute path:

```bash
python -m pip install /path/to/DjangoTaskCalendar/dist/django_task_calendar-0.1.5.1-py3-none-any.whl
python -m pip check
```

The package currently declares `Django==5.0` as a runtime dependency. Installation
can change the host's installed Django version to satisfy that requirement.
Follow the [developer guide](Diary/README.md) for PostgreSQL, application settings,
migrations, URLs, and optional validation middleware.

A successful build and metadata check do not run the application tests or verify
host integration. Run database tests against a separate PostgreSQL test database.
Building and checking distributions do not publish them to a package index.

## Build tool reference

See the [PyPA build guide](https://build.pypa.io/en/stable/how-to/basic-usage.html)
for build options and the [Twine documentation](https://twine.readthedocs.io/)
for distribution metadata checks.
