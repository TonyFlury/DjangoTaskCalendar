# DjangoTaskCalendar

Reusable task diaries for Django applications, with versioned templates, milestone dates, dependencies, and team ownership.

DjangoTaskCalendar creates named diaries for personal and team tasks.
Diaries can start empty and receive an approved task template later, preserving personal work.
It calculates task dates and identifies ready, blocked, late, and completed work.
Tasks can belong to a person, a configured group, or the whole team.
The application provides permission-checked Python APIs, Django pages, reusable templates, and validated template fixture transfer.

PostgreSQL is required for development, tests, and production.
The Python application name remains `Diary`.
Host applications own event lifecycle rules, user-group configuration, permitted diary scope, and integration presentation.
GarageSale integration code is not included in this repository.

## Repository status

This repository contains the extracted Diary implementation and its application history.
It is a source repository. Distribution packaging and release publication remain separate work.
The [TODO list](TODO.md) tracks packaging and the complete standalone README and documentation set.
No published package name, supported-version matrix, or release installation procedure is claimed yet.

## Existing documentation

- [Developer guide](Diary/README.md)
- [User guide](Diary/USER_GUIDE.md)
- [V1 implementation checklist](Diary/TODO_V1.md)
- [Design record](docs/design/event-calendar.md)

These documents preserve the implementation record from the original project.
Their conversion into a complete standalone documentation set remains open in [TODO.md](TODO.md).

## Extraction verification

The extracted application passed 225 tests against a separate PostgreSQL database.
The test run blocked GarageSale imports after database connection setup.
