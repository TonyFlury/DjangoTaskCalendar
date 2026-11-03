from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from Diary import api
from Diary.choices import DateKind
from Diary.models import EntryDependency


# Verifies DV1-006: Saved dependency validation.
@override_settings(DIARY_MANAGER='Officer', DIARY_USER='ExecMember')
class DependencyConcurrencyTests(TransactionTestCase):
    available_apps = ['Diary']

    def test_concurrent_opposite_links_cannot_form_a_cycle(self):
        self.assertEqual(connection.vendor, 'postgresql')
        actor = api.Actor('officer', frozenset({'Officer'}))
        template = api.DiaryTemplate.create(actor=actor, name='Concurrent template').key
        version = api.DiaryTemplate.from_key(actor=actor, key=template).create_version(number=1).key
        specs = [api.EntrySpec(name, DateKind.ANNUAL, month=1, day=1) for name in ('First', 'Second')]
        for spec in specs:
            api.DiaryTemplateVersion.from_key(actor=actor, key=version).add_entry(spec=spec)
        api.DiaryTemplateVersion.from_key(actor=actor, key=version).approve()
        key = api.DiaryInstance.create(actor=actor, template_version_key=version, event_ref='concurrency',
                                       name='Concurrent event', milestone_dates={}).key
        actor = api.Actor(actor.reference, actor.groups, frozenset({key}))
        start = Barrier(2)

        def save_link(entry, predecessor):
            close_old_connections()
            try:
                start.wait(timeout=10)
                api.DiaryInstance.from_key(actor=actor, key=key).set_predecessors(entry_key=entry.entry_key,
                                                                                  predecessor_keys=[
                                                                                      predecessor.entry_key])
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
