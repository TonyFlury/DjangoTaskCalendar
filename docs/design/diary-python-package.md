# Diary installable Python package

Status: Future requirement after V1. No later release number is assigned.

## Approved scope

DFUT-005 records the requirement to distribute Diary as an installable Python package.
Packaging is outside the V1 completion conditions.
The package must preserve Diary's independence from Garage Sale business models.

## Proposed implementation

Define package metadata and supported Python and Django versions.
Include Diary modules, management commands, migrations, templates, and static files in the distribution.
Document installation and host configuration in the developer guide.
Verify installation in a separate Django project with PostgreSQL.
Keep Garage Sale integration code outside the Diary package.

These steps describe a proposal. The packaging interface and distribution process are not approved requirements.

## Open decisions

Select the distribution name and import package name.
Select a versioning policy and release process.
Decide whether distribution uses a public package index, a private index, or release artifacts.
Define the supported Python, Django, and PostgreSQL versions.
Decide how package releases retain migration compatibility with existing deployments.

## Implementation status

No package metadata, distribution build, publication workflow, or installation verification is implemented for DFUT-005.
The existing standalone Diary tests provide evidence of separation from host business models.
Those tests do not verify an installed distribution.

## Language review

Reference: ASD-STE100 Issue 9.
A full dictionary and technical-name review remains incomplete.
This document does not claim full compliance.
