import sqlite3
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from scoreboard.models import Clan, Conduct, Game, Player, Source
from scoreboard.tests.helpers import in_window
from scoreboard.tests.test_aggregate import make_game
from tnnt import hardfought_utils, views
from tnnt.trophy_grid import generate_combo_grid_data

TEST_DGL_DB = 'dgamelaunch_test.db'


def login_player(client, name, clan=None, admin=False):
    user = User.objects.create_user(name, password='x')
    player = Player.objects.create(name=name, user=user, clan=clan,
                                   clan_admin=admin)
    client.force_login(user)
    return player


class ClanMgmtTests(TestCase):
    fixtures = ['sources']

    def setUp(self):
        self.clan = Clan.objects.create(name='Testers')
        self.alice = login_player(self.client, 'alice', self.clan, admin=True)
        patcher = mock.patch.object(hardfought_utils, 'DGL_DATABASE_PATH',
                                    TEST_DGL_DB)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_invalid_message_errors_show_on_the_message_form(self):
        resp = self.client.post('/clanmgmt',
                                {'set_message': '', 'message': 'bad\x01msg'})
        self.assertEqual(resp.status_code, 200)
        form = resp.context['set_message_form']
        self.assertTrue(form.is_bound)
        self.assertIn('message', form.errors)
        # the invite form is untouched (this used to receive the errors)
        self.assertFalse(resp.context['invite_member_form'].is_bound)
        self.clan.refresh_from_db()
        self.assertEqual(self.clan.message, '')

    def test_valid_message_is_saved(self):
        resp = self.client.post('/clanmgmt',
                                {'set_message': '', 'message': 'hello all'})
        self.assertEqual(resp.status_code, 200)
        self.clan.refresh_from_db()
        self.assertEqual(self.clan.message, 'hello all')

    def test_invite_dgl_user_creates_player_with_invite(self):
        # gimli exists in the test dgamelaunch database but not as a Player
        resp = self.client.post('/clanmgmt',
                                {'invite': '', 'invitee': 'gimli'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('errmsg', resp.context)
        gimli = Player.objects.get(name='gimli')
        self.assertIn(self.clan, gimli.invites.all())

    def test_invite_unknown_player(self):
        with self.assertLogs(level='WARNING'):
            resp = self.client.post('/clanmgmt',
                                    {'invite': '', 'invitee': 'zed'})
        self.assertEqual(resp.context['errmsg'], 'No such player exists')
        self.assertFalse(Player.objects.filter(name='zed').exists())

    def test_invite_reports_dgl_outage_not_no_such_player(self):
        with mock.patch.object(hardfought_utils, 'get_dgl_cursor',
                               side_effect=sqlite3.OperationalError('lock')), \
                self.assertLogs(level='ERROR'):
            resp = self.client.post('/clanmgmt',
                                    {'invite': '', 'invitee': 'zed'})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('temporarily unavailable', resp.context['errmsg'])


class GetPlayerTests(TestCase):

    def test_anonymous_user_has_no_player(self):
        # an unlinked Player must not be returned for an anonymous visitor
        Player.objects.create(name='alice')
        with self.assertRaises(Player.DoesNotExist):
            views.get_player(AnonymousUser())

    def test_leaderboards_for_anonymous_visitor(self):
        # a Player nobody is logged in as (user is NULL)
        Player.objects.create(name='alice')
        with self.assertNoLogs(level='ERROR'):
            resp = self.client.get('/leaderboards')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('myname', resp.context)


class LeaderboardTests(TestCase):
    fixtures = ['sources']

    def test_malformed_entry_is_dropped_not_fatal(self):
        src = Source.objects.get(server='hdf')
        a = Player.objects.create(name='a', total_games=1)
        a.max_score_game = make_game(a, src, won=False, mines_soko=False,
                                     death='killed by a newt', points=500)
        a.save()
        # b has games but no best game recorded: its stat is None
        Player.objects.create(name='b', total_games=1)
        with self.assertLogs(level='ERROR'):
            resp = self.client.get('/leaderboards')
        self.assertEqual(resp.status_code, 200)
        board = next(L for L in resp.context['leaderboards']
                     if L['id'] == 'maxscore')
        self.assertEqual([p['name'] for p in board['players']], ['a'])


class TrophyGridGamesViewTests(TestCase):
    URL = '/api/trophy-grid-games/'

    def test_non_numeric_entity_id_is_404_not_500(self):
        resp = self.client.get(self.URL, {'entity_type': 'player',
                                          'entity_id': 'abc', 'role': 'Val',
                                          'race': 'Hum', 'align': 'Law'})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'Entity not found')

    def test_missing_parameters_is_400(self):
        resp = self.client.get(self.URL, {'entity_type': 'player'})
        self.assertEqual(resp.status_code, 400)

    def test_valid_request(self):
        p = Player.objects.create(name='alice')
        resp = self.client.get(self.URL, {'entity_type': 'player',
                                          'entity_id': p.id, 'role': 'Val',
                                          'race': 'Hum', 'align': 'Law'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json()['games']),
                         {'mines_soko', 'male_ascensions',
                          'female_ascensions'})


class ScummedDefinitionTests(TestCase):
    fixtures = ['sources']

    def setUp(self):
        src = Source.objects.get(server='hdf')
        self.alice = Player.objects.create(name='alice', total_games=3)
        common = dict(won=False, mines_soko=False)
        make_game(self.alice, src, death='quit', turns=50, **common)
        make_game(self.alice, src, death='quit', turns=500, **common)
        make_game(self.alice, src, death='killed by a newt', turns=5,
                  **common)

    def test_every_page_agrees_on_what_is_scummed(self):
        home = self.client.get('/').context
        self.assertEqual(len(home['last10games']), 2)
        self.assertFalse(any(g['is_startscum'] for g in home['last10games']))

        allgames = self.client.get('/allgames').context
        self.assertEqual(len(allgames['games']), 2)

        scummed = self.client.get('/scummedgames').context
        self.assertEqual(scummed['total_scummed'], 1)
        self.assertEqual(scummed['scummed_list'][0]['scummed_games'], 1)

        plr = self.client.get('/player/alice?show_all=true').context
        self.assertEqual(len(plr['recentgames']), 2)

        recent = self.client.get('/player/alice').context
        self.assertEqual(
            [g['is_startscum'] for g in recent['recentgames']].count(True),
            1)


class TrophyStatusTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        self.src = Source.objects.get(server='hdf')
        self.clan = Clan.objects.create(name='C', total_games=3)
        a = Player.objects.create(name='a', clan=self.clan, total_games=2)
        b = Player.objects.create(name='b', clan=self.clan, total_games=1)
        neme = Conduct.objects.get(shortname='neme')
        vlad = Conduct.objects.get(shortname='vlad')
        win1 = make_game(a, self.src, role='Val', race='Dwa', align0='Law')
        win1.conducts.add(neme, vlad)
        make_game(a, self.src, role='Val', race='Hum', align0='Law')
        make_game(b, self.src, role='Arc', race='Gno', align0='Neu',
                  won=False)

    def test_flags_and_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            data = generate_combo_grid_data(self.clan, use_cache=False)
        self.assertLessEqual(len(ctx), 6)
        status = data['trophy_status']
        # one win kept the nemesis alive, another didn't
        self.assertTrue(status['keep_nemesis_alive'])
        self.assertTrue(status['keep_nemesis_alive_unobtainable'])
        self.assertTrue(status['keep_vlad_alive'])
        # no win kept Rodney alive, and one already didn't
        self.assertFalse(status['keep_rodney_alive'])
        self.assertTrue(status['keep_rodney_alive_unobtainable'])
        self.assertTrue(
            status['individual_conducts']['Never kill a quest nemesis'])
        self.assertFalse(status['all_conducts'])
        self.assertFalse(status['all_achievements'])
        self.assertFalse(status['great_roles']['Valkyrie'])
        self.assertTrue(status['never_scum'])
        grid = {(r['race_align'], c['role']): c for r in data['rows']
                for c in r['combos']}
        self.assertTrue(grid[('Dwa-Law', 'Val')]['asc_female'])
        self.assertTrue(grid[('Gno-Neu', 'Arc')]['mines_soko'])
        self.assertFalse(grid[('Gno-Neu', 'Arc')]['asc_female'])

    def test_player_without_wins(self):
        status = generate_combo_grid_data(
            Player.objects.get(name='b'), use_cache=False)['trophy_status']
        self.assertFalse(status['keep_nemesis_alive'])
        self.assertFalse(status['keep_nemesis_alive_unobtainable'])
        self.assertFalse(any(status['individual_conducts'].values()))


class AdminPanelTests(TestCase):
    fixtures = ['sources']

    def test_non_admin_is_refused(self):
        login_player(self.client, 'bob')
        self.assertEqual(self.client.get('/admin-panel').status_code, 403)

    def test_scummer_ips_come_from_one_batched_lookup(self):
        login_player(self.client, 'k2')  # in SITE_ADMINS
        for name, scummed in (('sam', 120), ('sue', 600), ('sal', 5)):
            Player.objects.create(name=name, games_scummed=scummed)
        with mock.patch.object(hardfought_utils, 'get_multi_account_ips',
                               return_value=[]), \
                mock.patch.object(hardfought_utils, 'get_players_last_ips',
                                  return_value={'sue': '10.0.0.9'}) as ips, \
                mock.patch.object(hardfought_utils,
                                  'get_player_last_ip') as single:
            resp = self.client.get('/admin-panel?refresh=1')
        self.assertEqual(resp.status_code, 200)
        # every scummer in one call, heaviest first; nothing per player
        ips.assert_called_once_with(['sue', 'sam'])
        single.assert_not_called()
        scummers = {p.name: p for p in resp.context['scummers']}
        self.assertEqual(sorted(scummers), ['sam', 'sue'])
        self.assertEqual(scummers['sue'].last_ip, '10.0.0.9')
        self.assertIsNone(scummers['sam'].last_ip)
        self.assertEqual(scummers['sue'].warning_level, 'serious')
        self.assertEqual(scummers['sam'].warning_level, 'warning')
        self.assertContains(resp, '10.0.0.9')

    def test_peak_rate_is_per_minute_with_levels(self):
        login_player(self.client, 'k2')
        src = Source.objects.get(server='hdf')
        base = datetime.fromtimestamp(in_window(days=2), timezone.utc)

        def scummer(name, games, gap):
            player = Player.objects.create(name=name, games_scummed=100)
            for i in range(games):
                make_game(player, src, death='quit', turns=1, won=False,
                          mines_soko=False,
                          start=base + timedelta(seconds=i * gap))

        scummer('slow', 6, 20)   # 3 in each of two minutes
        scummer('fast', 20, 3)   # 20 in one minute
        scummer('bot', 30, 2)    # 30 in one minute
        with mock.patch.object(hardfought_utils, 'get_multi_account_ips',
                               return_value=[]), \
                mock.patch.object(hardfought_utils, 'get_players_last_ips',
                                  return_value={}):
            resp = self.client.get('/admin-panel?refresh=1')
        self.assertEqual(resp.status_code, 200)
        rates = {p.name: (p.peak_scum_rate, p.scum_rate_level)
                 for p in resp.context['scummers']}
        self.assertEqual(rates, {'slow': (3, ''), 'fast': (20, 'fast'),
                                 'bot': (30, 'scripted')})
        self.assertContains(resp, 'Peak Games/Min')
        self.assertContains(resp, 'rate-scripted')
        self.assertNotContains(resp, 'Games/Sec')

    def test_instant_quit_share_with_levels(self):
        login_player(self.client, 'k2')
        src = Source.objects.get(server='hdf')
        base = datetime.fromtimestamp(in_window(days=2), timezone.utc)

        def scummer(name, lengths):
            player = Player.objects.create(name=name, games_scummed=100)
            for i, seconds in enumerate(lengths):
                make_game(player, src, death='quit', turns=1, won=False,
                          mines_soko=False,
                          start=base + timedelta(minutes=i),
                          length=timedelta(seconds=seconds))

        scummer('human', [6, 8, 7, 9, 6])          # 0%, median 7 s
        scummer('fast', [1, 5, 5, 5, 5, 0, 5, 5, 5, 5])   # 20%
        scummer('bot', [0, 1, 0, 0, 3, 1, 0, 0, 0, 2])    # 80%, median 0
        with mock.patch.object(hardfought_utils, 'get_multi_account_ips',
                               return_value=[]), \
                mock.patch.object(hardfought_utils, 'get_players_last_ips',
                                  return_value={}):
            resp = self.client.get('/admin-panel?refresh=1')
        self.assertEqual(resp.status_code, 200)
        got = {p.name: (p.instant_quit_pct, p.median_scum_seconds,
                        p.scum_duration_level)
               for p in resp.context['scummers']}
        self.assertEqual(got, {'human': (0, 7, ''),
                               'fast': (20, 5, 'fast'),
                               'bot': (80, 0, 'scripted')})
        self.assertContains(resp, 'Instant Quits')
        self.assertContains(resp, 'median 7 s')


class PlayersPageTests(TestCase):
    """
    A Player row is also created by a login or by a clan invite, before
    any game is played. The players page and the index's player count
    only show players with at least one game, like the API does.
    """

    def setUp(self):
        self.clan = Clan.objects.create(name='Testers')
        Player.objects.create(name='alice', total_games=3, wins=1,
                              clan=self.clan)
        Player.objects.create(name='bob', total_games=2)
        Player.objects.create(name='ghost', clan=self.clan)

    def test_only_players_with_games_are_listed(self):
        resp = self.client.get('/players')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([p.name for p in resp.context['players']],
                         ['alice', 'bob'])
        self.assertNotContains(resp, 'ghost')

    def test_index_player_count_uses_the_same_rule(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['numplayers'], 2)

    def test_games_less_player_still_has_a_page(self):
        self.assertEqual(self.client.get('/player/ghost').status_code, 200)

    def test_clan_column_does_not_query_per_player(self):
        with CaptureQueriesContext(connection) as few:
            self.client.get('/players')
        for i in range(20):
            Player.objects.create(name='p%d' % i, total_games=1,
                                  clan=self.clan)
        with CaptureQueriesContext(connection) as many:
            self.client.get('/players')
        self.assertEqual(len(many), len(few))
