# DjangoTaskCalendar repository TODO

## README and documentation

**Must have before publication:** Complete the [documentation publication plan](docs/design/documentation-publication-plan.md), including all three audience guides, the short README, verified examples, and Read the Docs publication setup. Documentation is a release gate for package publication and public documentation launch.

- [ ] **DOC-001:** Write the complete repository README.
  Provide a short product introduction, main features, representative screenshot, prerequisites, licence, and links to the three guides. Keep the full quick-start in the documentation.
- [ ] **DOC-002:** Build the standalone developer guide.
  Document settings, PostgreSQL setup, migrations, identity adapters, permissions, callable APIs, UI integration, and management commands.
- [ ] **DOC-003:** Build the standalone user and administrator guides.
  Document templates, diaries, ownership, dependencies, task completion, orphaned tasks, and validated fixture transfers.
- [ ] **DOC-004:** Review preserved documentation and design examples for standalone use.
  Replace obsolete host-specific instructions and broken links. Review dashboard previews that refer to GarageSale assets.
- [ ] **DOC-005:** Verify documentation examples in a minimal Django host with PostgreSQL.
  Keep test data in a separate PostgreSQL database.
- [ ] **DOC-006:** Complete the ASD-STE100 Issue 9 dictionary and technical-name review.
  English is the current documentation language. Localization is not required.
- [ ] **DOC-007:** Write the minimal, end-to-end quick-start guide, including task templates and Django HTML templates.
- [ ] **DOC-008:** Configure and verify Read the Docs publication through the GitHub integration, including strict documentation builds, release versions, and pull-request previews.
- [ ] **DOC-009:** Reconcile README installation and packaging claims with `pyproject.toml` and verified distribution contents before publication.

## Packaging and release

- [ ] **PKG-001:** Implement installable distribution packaging under the existing DFUT-005 requirement.
  Include the application modules, management commands, migrations, templates, and static assets.
- [ ] **PKG-002:** Decide the distribution name, license, version policy, supported versions, and publication location.
  The repository name is DjangoTaskCalendar. The current Python import name remains `Diary`.
- [ ] **PKG-003:** Verify installation and migration compatibility in an independent Django project.
- [ ] **PKG-004:** Define automated package checks and the release process.

## Scope

GarageSale event creation, settings, URL adapters, page wrappers, and dashboard integration belong to the host repository.
This repository must not acquire dependencies on GarageSale business models.
The existing [Diary V1 checklist](Diary/TODO_V1.md) retains its original DV1 and DFUT identifiers.
