from django.db import models


class DateKind(models.TextChoices):
    SOURCE = 'source', 'Source date'
    ANNUAL = 'annual', 'Annual date'
    RELATIVE = 'relative', 'Calculated date'
    ONCE = 'once', 'One-time date'


class OwnerKind(models.TextChoices):
    TEAM = 'team', 'Whole team'
    PERSON = 'person', 'Person'
    ROLE = 'role', 'Role'


class VersionStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    APPROVED = 'approved', 'Approved'
