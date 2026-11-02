from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from Diary import api
from Diary.choices import DateKind
from Diary.models import EntryDependency


@override_settings(DIARY_PERMISSION_GROUPS={'use': ('Officer',), 'edit': ('Officer',)})
class DependencyConcurrencyTests(TransactionTestCase):
    available_apps = ['Diary']

    def test_concurrent_opposite_links_cannot_form_a_cycle(self):
        self.assertEqual(connection.vendor, 'postgresql')
        actor = api.Actor('officer', frozenset({'Officer'}))
        template = api.create_template(actor=actor, name='Concurrent template')
        version = api.create_template_version(actor=actor, template_key=template, number=1)
        specs = [api.EntrySpec(name, DateKind.ANNUAL, month=1, day=1) for name in ('First', 'Second')]
        for spec in specs:
            api.add_template_entry(actor=actor, template_version_key=version, spec=spec)
        api.approve_template_version(actor=actor, template_version_key=version)
        key = api.create_calendar(actor=actor, template_version_key=version, event_ref='concurrency',
                                  name='Concurrent event', event_year=2027, milestone_dates={})
        actor = api.Actor(actor.reference, actor.groups, frozenset({key}))
        start = Barrier(2)

        def save_link(entry, predecessor):
            close_old_connections()
            try:
                start.wait(timeout=10)
                api.set_predecessors(actor=actor, scope_key=key, entry_key=entry.entry_key,
                                     predecessor_keys=[predecessor.entry_key])
                return 'saved'
            except ValidationError:
                return 'rejected'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(save_link, specs[0], specs[1])
            second = pool.submit(save_link, specs[1], specs[0])
            results = [first.result(timeout=20), second.result(timeout=20)]
        self.assertCountEqual(results, ['saved', 'rejected'])
        self.assertEqual(EntryDependency.objects.count(), 1)
