# Documentation publication plan

Status: agreed scope for later implementation. **Must have before publication.**

This plan is a release gate for package publication and public documentation launch.
Recording it does not implement the guides or configure hosting. Complete DOC-001
through DOC-009 in the repository TODO before publication.

## Audience split

Provide three audience-focused guides, a short root README, and a shared glossary.
The integration guide should have separate reference pages so it remains navigable
as the API grows. The documentation homepage must offer three obvious entry points:
Get started, Integrate Diary, and Use Diary.

### 1. Quick-start guide

Audience: a Django developer trying the app for the first time.

Use one complete example taking an existing Django project to a displayed diary
containing tasks:

1. Explain prerequisites and installation.
2. Register `Diary`, configure required settings, and apply migrations.
3. Create access groups and memberships, then validate configuration.
4. Configure authentication, URLs, and trusted diary scope.
5. Create a minimal task template, then a diary with milestone dates.
6. Render the diary using supplied Django HTML templates, stylesheet, and required scripts.
7. Open the page and complete a task.

Include a minimal host base template and the exact integration code needed.
Explicitly distinguish reusable task templates from Django HTML templates.
Registering default URLs alone does not grant diary access; trusted scope is part
of the minimum working setup. Link advanced options to the integration guide.

Acceptance: a reader can see and complete a task in their own Django project.

### 2. Integration guide

Audience: developers maintaining a host application.

| Area | Required coverage |
| --- | --- |
| Application boundary | Host responsibilities, diary UUIDs, opaque references, lifecycle, user model, database requirements |
| Settings reference | Every supported setting, type, required/default value, validation, example |
| Access and ownership | Users, managers, ownership groups, trusted scope, personal-task privacy |
| Templates and diary creation | Template versions and approval, date rules, milestone inputs, creation and closure |
| Page integration | Views, URL names, selectors, context, authentication, complete pages and reusable partials |
| Styling | `.diary` namespace, supported component/state classes, stylesheet loading, override examples |
| Python API | Public classes and methods, signatures, arguments, return structures, exceptions, permissions, repeat-call behaviour |
| Data extraction | Diary/task reads, personal tasks, readiness, lateness, search, blockers, completion history |
| HTTP data API | Routes, authentication, selectors, response examples, errors, privacy, caching |
| Operations | Configuration validation, template import/export commands, deployment, troubleshooting |

Cover the public surface of `Diary.api`, including `Actor`, `OwnerDirectory`,
`EntrySpec`, and the diary/template classes. Explain workflows before detailed
reference entries. Use one consistent example: create a template, instantiate a
diary, connect its key to a host record, display it, and retrieve task data.

### 3. UI user guide

Audience: ordinary users and managers; assume no Python knowledge.

Provide two clear reading paths:

| Ordinary users | Managers |
| --- | --- |
| Understand diaries, tasks, dates, ownership | Understand manager permissions |
| Find tasks in My Diary | Use manager diary filters |
| Interpret Ready, Blocked, Late, Completed | Assign people, groups, whole-team work |
| Create personal tasks | Create tasks for others |
| Edit permitted due dates | Adjust permitted dates and resolve orphaned ownership |
| Inspect predecessors and complete tasks | Use Close all and inspect completion history |
| Understand privacy and shared completion | Create and version templates, configure dates and predecessors |
| Resolve common problems | Add a new task to a template for future diaries |

Use short procedures, actual button labels, and screenshots of significant screens.
Describe progress through implemented readiness, blocking, lateness, and completion;
do not imply an editable in-progress workflow exists. Explain editing restrictions
alongside procedures. Make clear that template changes leave existing diaries unchanged.
Explain that diary creation and closure depend on the host site's workflow.

## Root README

Aim for approximately 250–400 words:

- Purpose and intended users.
- Main features: reusable versioned task templates, milestone-based dates,
  dependencies, personal/group/team ownership, user and manager pages, callable
  and data APIs.
- One representative screenshot.
- Essential prerequisites and link to the quick-start.
- Links to all three guides and licence information.

Remove extraction history, historical test counts, and internal implementation
tracking from the introduction. Describe date-ordered task lists accurately;
do not suggest a month-grid calendar is available.

## Proposed source layout

```text
README.md
docs/
    index.md
    quickstart.md
    integration/
        index.md
        configuration.md
        access-and-ownership.md
        templates-and-diaries.md
        pages-and-embedding.md
        styling.md
        python-api.md
        http-api.md
        operations.md
    user-guide/
        index.md
        everyday-tasks.md
        manager-tasks.md
        templates.md
        troubleshooting.md
    glossary.md
    release-notes.md
    _static/
    design/
```

Keep engineering records and backlog material outside the primary reader journeys.
Each topic should have one canonical location; cross-link rather than duplicate it.

## Read the Docs publication

Proposed tooling: Sphinx with Markdown through MyST, a repository-root
`.readthedocs.yaml`, and pinned documentation dependencies. Configure strict builds,
release-version documentation, and GitHub-triggered publication with pull-request
previews. Verify hosting configuration during implementation.

- [Read the Docs configuration reference](https://docs.readthedocs.com/platform/stable/config-file/v2.html)
- [Pull-request preview setup](https://docs.readthedocs.com/platform/stable/guides/pull-requests.html)

## Implementation sequence and acceptance

1. Audit existing documentation against current code; separate supported behaviour
   from historical decisions, proposals, and backlog.
2. Build and verify the quick-start in a clean minimal Django host using PostgreSQL.
   Keep test data in a separate PostgreSQL database.
3. Restructure `Diary/README.md` and `Diary/HOST_EMBEDDING.md` into integration chapters.
4. Adapt `Diary/USER_GUIDE.md` into ordinary-user and manager journeys.
5. Replace old guide locations with links to canonical replacements; repair links
   and remove obsolete host-specific examples and asset dependencies.
6. Write the short README and configure publication.
7. Check links, rendered pages, public API coverage, screenshots, and the complete
   quick-start. Complete the existing English terminology review (DOC-006).

Reconcile packaging and installation statements before publication: `pyproject.toml`
declares distribution metadata and Python/Django requirements, while the existing
README says packaging and installation are undefined. Verify distribution contents
and installation before making compatibility or availability claims. Do not infer
a supported-version matrix from untested versions.

Publication is ready only when the three guides and README are complete, examples
work against the release being published, documentation builds pass, navigation and
links are checked, and GitHub-to-Read-the-Docs publication is verified.
