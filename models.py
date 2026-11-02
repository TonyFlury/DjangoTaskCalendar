import uuid
from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower

from .choices import DateKind, OwnerKind, VersionStatus
from .date_rules import resolve_date


def owner_shape():
    return (Q(owner_kind='team', person_ref='', role_ref='')
            | (Q(owner_kind='person', role_ref='') & ~Q(person_ref=''))
            | (Q(owner_kind='role', person_ref='') & ~Q(role_ref='')))


def date_shape():
    common = Q(month__isnull=True, day__isnull=True, year_offset=0)
    return (
        (Q(date_kind='source', fixed_date__isnull=True, day_offset=0) & common & Q(milestone__isnull=False))
        | (Q(date_kind='relative', fixed_date__isnull=True) & common & Q(milestone__isnull=False))
        | (Q(date_kind='annual', milestone__isnull=True, fixed_date__isnull=True, day_offset=0,
             month__isnull=False, day__isnull=False, month__gte=1, month__lte=12, day__gte=1, day__lte=31)
           & ~Q(month__in=(4, 6, 9, 11), day__gt=30) & ~Q(month=2, day__gt=29))
        | Q(date_kind='once', milestone__isnull=True, month__isnull=True, day__isnull=True,
            year_offset=0, day_offset=0, fixed_date__isnull=False)
    )


class ValidatedModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Milestone(ValidatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ('name',)
        constraints = [models.CheckConstraint(check=~Q(name=''), name='diary_milestone_name_present')]

    def __str__(self):
        return self.label

    def clean(self):
        super().clean()
        if not self._state.adding and type(self).objects.get(pk=self.pk).name != self.name:
            raise ValidationError({'name': 'A milestone name cannot change. Define another milestone.'})


class CalendarTemplate(ValidatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(Lower('name'), name='diary_template_name_ci'),
            models.CheckConstraint(check=~Q(name=''), name='diary_template_name_present'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({'name': 'Enter a template name.'})


class TemplateVersion(ValidatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(CalendarTemplate, on_delete=models.PROTECT, related_name='versions')
    number = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=VersionStatus.choices, default=VersionStatus.DRAFT)
    created_by_ref = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by_ref = models.CharField(max_length=200, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('template', 'number')
        constraints = [
            models.UniqueConstraint(fields=('template', 'number'), name='diary_template_version_unique'),
            models.CheckConstraint(check=Q(number__gte=1), name='diary_version_number_positive'),
            models.CheckConstraint(
                check=(Q(status='draft', approved_at__isnull=True, approved_by_ref='')
                       | (Q(status='approved', approved_at__isnull=False) & ~Q(approved_by_ref=''))),
                name='diary_version_approval_state',
            ),
        ]

    def __str__(self):
        return f'{self.template} / {self.number}'

    def clean(self):
        super().clean()
        if not self._state.adding:
            old = type(self).objects.get(pk=self.pk)
            if old.status == VersionStatus.APPROVED:
                fields = ('template_id', 'number', 'status', 'created_by_ref', 'approved_by_ref', 'approved_at')
                if any(getattr(old, field) != getattr(self, field) for field in fields):
                    raise ValidationError('An approved version cannot change. Create a new version.')


class EventCalendar(ValidatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_ref = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=160)
    event_year = models.PositiveSmallIntegerField()
    template_version = models.ForeignKey(TemplateVersion, on_delete=models.PROTECT, related_name='calendars')
    created_by_ref = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('event_year', 'name')
        constraints = [
            models.CheckConstraint(check=Q(event_year__gte=1, event_year__lte=9999), name='diary_calendar_year_valid'),
            models.CheckConstraint(check=~Q(event_ref=''), name='diary_calendar_event_ref_present'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.event_ref = self.event_ref.strip()
        self.name = self.name.strip()
        if not self.event_ref or not self.name:
            raise ValidationError('Enter an event reference and calendar name.')
        if self.template_version_id and self.template_version.status != VersionStatus.APPROVED:
            raise ValidationError({'template_version': 'Select an approved template version.'})

    def date_context(self):
        return dict(self.milestone_dates.values_list('milestone__name', 'date'))


class CalendarMilestone(ValidatedModel):
    calendar = models.ForeignKey(EventCalendar, on_delete=models.CASCADE, related_name='milestone_dates')
    milestone = models.ForeignKey(Milestone, on_delete=models.PROTECT, related_name='calendar_dates')
    date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=('calendar', 'milestone'), name='diary_calendar_milestone_unique')]


class EntryFields(ValidatedModel):
    entry_key = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    date_kind = models.CharField(max_length=12, choices=DateKind.choices)
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    month = models.PositiveSmallIntegerField(null=True, blank=True)
    day = models.PositiveSmallIntegerField(null=True, blank=True)
    year_offset = models.SmallIntegerField(default=0)
    day_offset = models.IntegerField(default=0)
    fixed_date = models.DateField(null=True, blank=True)
    owner_kind = models.CharField(max_length=12, choices=OwnerKind.choices, default=OwnerKind.TEAM)
    person_ref = models.CharField(max_length=200, blank=True)
    role_ref = models.CharField(max_length=200, blank=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(check=date_shape(), name='%(app_label)s_%(class)s_date_shape'),
            models.CheckConstraint(check=owner_shape(), name='%(app_label)s_%(class)s_owner_shape'),
            models.CheckConstraint(check=~Q(name=''), name='%(app_label)s_%(class)s_name_present'),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        self.person_ref = self.person_ref.strip()
        self.role_ref = self.role_ref.strip()
        if not self.name:
            raise ValidationError({'name': 'Enter an entry name.'})
        if self.date_kind == DateKind.ANNUAL and self.month is not None and self.day is not None:
            try:
                date(2000, self.month, self.day)
            except (ValueError, TypeError):
                raise ValidationError('Select a valid month and day.')
        if not self._state.adding:
            old_key = type(self).objects.values_list('entry_key', flat=True).get(pk=self.pk)
            if old_key != self.entry_key:
                raise ValidationError({'entry_key': 'An entry key cannot change.'})

    def resolve_date(self, *, event_year, source_dates):
        return resolve_date(kind=self.date_kind, event_year=event_year, source_dates=source_dates,
                            source=self.milestone.name if self.milestone_id else '', month=self.month, day=self.day,
                            year_offset=self.year_offset, day_offset=self.day_offset, fixed_date=self.fixed_date)


class TemplateEntry(EntryFields):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.ForeignKey(TemplateVersion, on_delete=models.PROTECT, related_name='entries')
    predecessors = models.ManyToManyField('self', symmetrical=False, through='TemplateDependency',
                                         through_fields=('entry', 'predecessor'), related_name='successors')

    class Meta(EntryFields.Meta):
        abstract = False
        ordering = ('name',)
        constraints = EntryFields.Meta.constraints + [
            models.UniqueConstraint(fields=('version', 'entry_key'), name='diary_template_entry_key_unique'),
            models.UniqueConstraint(Lower('name'), 'version', name='diary_template_entry_name_ci'),
            models.CheckConstraint(check=~Q(date_kind='once'), name='diary_template_entry_reusable'),
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            version = TemplateVersion.objects.select_for_update().get(pk=self.version_id)
            if version.status != VersionStatus.DRAFT:
                raise ValidationError('Entries in an approved template version cannot change.')
            if not self._state.adding and type(self).objects.get(pk=self.pk).version_id != self.version_id:
                raise ValidationError('An entry cannot move to another version.')
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            version = TemplateVersion.objects.select_for_update().get(pk=self.version_id)
            if version.status != VersionStatus.DRAFT:
                raise ValidationError('Entries in an approved template version cannot be deleted.')
            return super().delete(*args, **kwargs)


class CalendarEntry(EntryFields):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    calendar = models.ForeignKey(EventCalendar, on_delete=models.PROTECT, related_name='entries')
    source_entry = models.ForeignKey(TemplateEntry, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='event_entries')
    created_by_ref = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_ref = models.CharField(max_length=200, blank=True)
    completed_due_date = models.DateField(null=True, blank=True)
    predecessors = models.ManyToManyField('self', symmetrical=False, through='EntryDependency',
                                         through_fields=('entry', 'predecessor'), related_name='successors')

    class Meta(EntryFields.Meta):
        abstract = False
        ordering = ('name',)
        constraints = EntryFields.Meta.constraints + [
            models.UniqueConstraint(fields=('calendar', 'entry_key'), name='diary_calendar_entry_key_unique'),
            models.UniqueConstraint(Lower('name'), 'calendar', name='diary_calendar_entry_name_ci'),
            models.CheckConstraint(
                check=(Q(completed_at__isnull=True, completed_by_ref='', completed_due_date__isnull=True)
                       | (Q(completed_at__isnull=False) & ~Q(completed_by_ref=''))),
                name='diary_entry_completion_state',
            ),
        ]

    def clean(self):
        super().clean()
        if self.source_entry_id and self.calendar_id:
            if (self.source_entry.version_id != self.calendar.template_version_id
                    or self.source_entry.entry_key != self.entry_key):
                raise ValidationError({'source_entry': 'The source must match this calendar version and entry key.'})
        old = type(self).objects.get(pk=self.pk) if not self._state.adding else None
        if old and old.calendar_id != self.calendar_id:
            raise ValidationError('An entry cannot move to another event calendar.')
        if old and old.completed_at is not None:
            if any(getattr(old, field.attname) != getattr(self, field.attname)
                   for field in self._meta.concrete_fields):
                raise ValidationError('A completed entry cannot change.')
        elif self.completed_at is not None:
            self.completed_due_date = self.resolve_date(
                event_year=self.calendar.event_year, source_dates=self.calendar.date_context())

    @property
    def due_date(self):
        if self.completed_at is not None:
            return self.completed_due_date
        return self.resolve_date(event_year=self.calendar.event_year, source_dates=self.calendar.date_context())

    @property
    def is_ready(self):
        return self.completed_at is None and not self.predecessors.filter(completed_at__isnull=True).exists()


class DependencyFields(ValidatedModel):
    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(check=~Q(entry=F('predecessor')), name='%(app_label)s_%(class)s_not_self'),
            models.UniqueConstraint(fields=('entry', 'predecessor'), name='%(app_label)s_%(class)s_unique'),
        ]

    def clean(self):
        super().clean()
        if not self.entry_id or not self.predecessor_id:
            return
        if self.entry_id == self.predecessor_id:
            raise ValidationError('A task cannot be its own predecessor.')
        if getattr(self.entry, self.scope_field) != getattr(self.predecessor, self.scope_field):
            raise ValidationError('Predecessors must belong to the same calendar or template version.')
        links = type(self).objects.filter(**{f'entry__{self.scope_field}': getattr(self.entry, self.scope_field)})
        if not self._state.adding:
            links = links.exclude(pk=self.pk)
        successors = {}
        for entry_id, predecessor_id in links.values_list('entry_id', 'predecessor_id'):
            successors.setdefault(predecessor_id, set()).add(entry_id)
        seen, pending = set(), [self.entry_id]
        while pending:
            task = pending.pop()
            if task == self.predecessor_id:
                raise ValidationError('This predecessor would create a circular dependency.')
            if task not in seen:
                seen.add(task)
                pending.extend(successors.get(task, ()))

    def save(self, *args, **kwargs):
        with transaction.atomic():
            scope = self.scope_model.objects.select_for_update().get(pk=getattr(self.entry, self.scope_field))
            if isinstance(scope, TemplateVersion) and scope.status != VersionStatus.DRAFT:
                raise ValidationError('Dependencies in an approved template version cannot change.')
            if not self._state.adding:
                old = type(self).objects.get(pk=self.pk)
                if (old.entry_id, old.predecessor_id) != (self.entry_id, self.predecessor_id):
                    raise ValidationError('Delete the dependency before replacing its endpoints.')
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            scope = self.scope_model.objects.select_for_update().get(pk=getattr(self.entry, self.scope_field))
            if isinstance(scope, TemplateVersion) and scope.status != VersionStatus.DRAFT:
                raise ValidationError('Dependencies in an approved template version cannot change.')
            return super().delete(*args, **kwargs)


class TemplateDependency(DependencyFields):
    scope_field = 'version_id'
    scope_model = TemplateVersion
    entry = models.ForeignKey(TemplateEntry, on_delete=models.CASCADE, related_name='predecessor_links')
    predecessor = models.ForeignKey(TemplateEntry, on_delete=models.PROTECT, related_name='successor_links')

    class Meta(DependencyFields.Meta):
        abstract = False


class EntryDependency(DependencyFields):
    scope_field = 'calendar_id'
    scope_model = EventCalendar
    entry = models.ForeignKey(CalendarEntry, on_delete=models.CASCADE, related_name='predecessor_links')
    predecessor = models.ForeignKey(CalendarEntry, on_delete=models.PROTECT, related_name='successor_links')

    class Meta(DependencyFields.Meta):
        abstract = False
