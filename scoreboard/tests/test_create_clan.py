"""
Creating a clan is all or nothing (2026-11-01): the clan, its creator's
membership and the withdrawal of their invitations happen in one
transaction, and a second submit of the form can't make a second clan.
"""
from unittest import mock

from django.db import transaction
from django.test import RequestFactory, TestCase

import tnnt.settings
from scoreboard.models import Clan, Player
from scoreboard.tests.test_views import login_player
from tnnt import views


class CreateClanTests(TestCase):

    def setUp(self):
        patcher = mock.patch.object(tnnt.settings, 'CLAN_FREEZE_TIME', None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bob = login_player(self.client, 'bob')
        self.bob.invites.add(Clan.objects.create(name='Testers'))

    def create(self, name):
        return self.client.post('/clanmgmt',
                                {'create_clan': '', 'clan_name': name})

    def test_creator_joins_as_admin_and_invitations_go(self):
        resp = self.create('Combo Crew')
        self.assertNotIn('errmsg', resp.context)
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.clan.name, 'Combo Crew')
        self.assertTrue(self.bob.clan_admin)
        self.assertFalse(self.bob.invites.exists())

    def test_a_failure_part_way_leaves_no_clan(self):
        with mock.patch.object(Player, 'save',
                               side_effect=RuntimeError('database gone')):
            with self.assertRaises(RuntimeError), \
                    self.assertLogs('django.request', level='ERROR'):
                self.create('Combo Crew')
        self.assertFalse(Clan.objects.filter(name='Combo Crew').exists())
        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.clan)
        self.assertTrue(self.bob.invites.exists())

    def test_name_taken_after_the_check_shows_the_message(self):
        def other_request_first(*args, **kwargs):
            # someone else creates the clan after this request's exists()
            # check, just before its transaction starts
            Clan.objects.create(name='Combo Crew')
            return transaction.atomic(*args, **kwargs)
        with mock.patch.object(views, 'transaction',
                               mock.Mock(atomic=other_request_first)):
            resp = self.create('Combo Crew')
        self.assertEqual(resp.context['errmsg'], 'That clan already exists')
        self.assertEqual(Clan.objects.filter(name='Combo Crew').count(), 1)
        self.bob.refresh_from_db()
        self.assertIsNone(self.bob.clan)

    def test_form_sent_twice_makes_one_clan(self):
        # the second submit's request loaded bob before the first one made
        # him a clan admin
        stale = Player.objects.get(pk=self.bob.pk)
        self.create('Combo Crew')
        request = RequestFactory().post(
            '/clanmgmt', {'create_clan': '', 'clan_name': 'Second Clan'})
        request.user = self.bob.user
        ctx = {}
        views.ClanMgmtView().create_clan(request, stale, ctx)
        self.assertEqual(ctx['errmsg'], 'You are already in a clan')
        self.assertFalse(Clan.objects.filter(name='Second Clan').exists())
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.clan.name, 'Combo Crew')
