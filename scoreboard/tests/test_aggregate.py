import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests
from django.test import TestCase

import tnnt.settings
from scoreboard.management.commands import aggregate
from scoreboard.models import (
    Achievement, Clan, Conduct, Game, Player, Source, Trophy
)
from scoreboard.tests.helpers import in_window
from scoreboard.trophy_defs import achievement_count_trophies, feature_trophies

_game_seq = [0]


def make_game(player, source, role='Val', race='Hum', align0='Law',
              gender0='Fem', won=True, mines_soko=True, death='ascended',
              turns=20000, points=1000000, start=None,
              length=timedelta(hours=1)):
    """
    Create a Game with all non-null fields filled in and unique times, or
    starting at `start` (an aware datetime) when given; `length` is the
    game's realtime, wallclock and endtime - starttime.
    """
    _game_seq[0] += 1
    if start is None:
        start = datetime.fromtimestamp(
            in_window(seconds=_game_seq[0] * 3600), timezone.utc)
    return Game.objects.create(
        version='3.6.7', role=role, race=race, gender=gender0, align=align0,
        gender0=gender0, align0=align0, points=points, turns=turns,
        realtime=length, wallclock=length,
        maxlvl=50, starttime=start, endtime=start + length,
        death=death, normalized_death=None, won=won, mines_soko=mines_soko,
        player=player, source=source)


class ClanAggregationTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        aggregate.load_static_data()
        self.src = Source.objects.get(server='hdf')
        self.clan = Clan.objects.create(name='Testers')
        self.alice = Player.objects.create(name='alice', clan=self.clan,
                                           clan_admin=True)
        self.bob = Player.objects.create(name='bob', clan=self.clan)

    def run_aggregate(self):
        aggregate.aggregatePlayerData()
        aggregate.aggregateClanData()

    def test_clan_loses_trophy_when_contributing_member_leaves(self):
        # alice alone earns Great Valkyrie for the clan
        for race, align in [('Dwa', 'Law'), ('Hum', 'Law'), ('Hum', 'Neu')]:
            make_game(self.alice, self.src, role='Val', race=race,
                      align0=align)
        self.run_aggregate()
        self.assertTrue(
            self.clan.trophies.filter(name='Great Valkyrie').exists())
        self.assertTrue(
            self.alice.trophies.filter(name='Great Valkyrie').exists())

        self.alice.clan = None
        self.alice.save()
        self.run_aggregate()
        # the clan no longer has the games behind the trophy...
        self.assertFalse(
            self.clan.trophies.filter(name='Great Valkyrie').exists())
        # ...but alice herself keeps it
        self.assertTrue(
            self.alice.trophies.filter(name='Great Valkyrie').exists())

    def test_games_scummed_uses_the_shared_definition(self):
        make_game(self.bob, self.src, won=False, mines_soko=False,
                  death='quit', turns=50)
        make_game(self.bob, self.src, won=False, mines_soko=False,
                  death='escaped', turns=100)
        make_game(self.bob, self.src, won=False, mines_soko=False,
                  death='quit', turns=500)
        make_game(self.bob, self.src, won=False, mines_soko=False,
                  death='killed by a newt', turns=5)
        self.run_aggregate()
        self.bob.refresh_from_db()
        self.clan.refresh_from_db()
        self.assertEqual(self.bob.games_scummed, 2)
        self.assertEqual(self.bob.total_games, 4)
        self.assertEqual(self.clan.games_scummed, 2)
        self.assertFalse(
            self.bob.trophies.filter(name='Never Scum a Game').exists())

    def test_never_scum_awarded_to_clean_player(self):
        make_game(self.alice, self.src)
        self.run_aggregate()
        self.assertTrue(
            self.alice.trophies.filter(name='Never Scum a Game').exists())
        self.assertTrue(
            self.clan.trophies.filter(name='Never Scum a Game').exists())


class AchievementTrophyTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        aggregate.load_static_data()
        self.src = Source.objects.get(server='hdf')
        self.clan = Clan.objects.create(name='Testers')
        self.alice = Player.objects.create(name='alice', clan=self.clan)
        self.bob = Player.objects.create(name='bob', clan=self.clan)
        # achievements that earn no feature trophy, in a fixed order
        self.plain = list(Achievement.objects.exclude(
            define__in=feature_trophies.values()).order_by('id'))

    def death(self, player, achievements):
        game = make_game(player, self.src, won=False, mines_soko=False,
                         death='killed by a jackal')
        game.achievements.add(*achievements)

    def run_aggregate(self):
        aggregate.aggregatePlayerData()
        aggregate.aggregateClanData()

    def trophies(self, player_or_clan):
        return set(player_or_clan.trophies.values_list('name', flat=True))

    def test_count_trophies_are_inclusive_and_distinct(self):
        # alice: exactly 20 distinct, one of them in two games
        self.death(self.alice, self.plain[:20])
        self.death(self.alice, self.plain[19:20])
        self.run_aggregate()
        self.assertIn('20 Achievements', self.trophies(self.alice))
        self.assertNotIn('50 Achievements', self.trophies(self.alice))

    def test_clan_counts_the_union_of_its_members(self):
        # alice 30, bob 40, 10 shared: the clan has 60 distinct (70 summed)
        self.death(self.alice, self.plain[:30])
        self.death(self.bob, self.plain[20:60])
        self.run_aggregate()
        self.assertNotIn('50 Achievements', self.trophies(self.alice))
        self.assertNotIn('50 Achievements', self.trophies(self.bob))
        clan = self.trophies(self.clan)
        self.assertIn('50 Achievements', clan)
        self.assertNotIn('100 Achievements', clan)
        self.assertNotIn('All Achievements', clan)

    def test_feature_trophy_from_any_game(self):
        # a plain death, neither a win nor mines_soko, still counts
        self.death(self.alice,
                   [Achievement.objects.get(define='A_FOUND_KITTEN')])
        self.run_aggregate()
        self.assertEqual(
            self.trophies(self.alice) & set(feature_trophies),
            {'Robot Finds Kitten'})
        self.assertIn('Robot Finds Kitten', self.trophies(self.clan))
        self.assertNotIn('Robot Finds Kitten', self.trophies(self.bob))

        self.alice.clan = None
        self.alice.save()
        self.run_aggregate()
        self.assertNotIn('Robot Finds Kitten', self.trophies(self.clan))
        self.assertIn('Robot Finds Kitten', self.trophies(self.alice))


class AllAscensionsFieldTests(TestCase):
    # unique_conducts and latest_start_asc, behind the Most Conducts in All
    # Ascensions and Latest Start Time of an Ascension leaderboards
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def setUp(self):
        aggregate.load_static_data()
        self.src = Source.objects.get(server='hdf')
        self.clan = Clan.objects.create(name='Testers')
        self.alice = Player.objects.create(name='alice', clan=self.clan)
        self.bob = Player.objects.create(name='bob', clan=self.clan)
        self.carol = Player.objects.create(name='carol')
        self.conducts = list(Conduct.objects.order_by('id'))

    def game(self, player, conducts, won=True, **kwargs):
        game = make_game(player, self.src, won=won, mines_soko=won,
                         death='ascended' if won else 'killed by a jackal',
                         **kwargs)
        game.conducts.add(*conducts)
        return game

    def run_aggregate(self):
        aggregate.aggregatePlayerData()
        aggregate.aggregateClanData()
        for entity in (self.alice, self.bob, self.carol, self.clan):
            entity.refresh_from_db()

    def test_unique_conducts_are_distinct_and_from_ascensions_only(self):
        c = self.conducts
        self.game(self.alice, c[0:2])
        self.game(self.alice, c[1:3])
        # a death keeps conducts too, but it is not an ascension
        self.game(self.alice, c[10:11], won=False)
        self.game(self.bob, c[2:6])
        self.game(self.carol, c[0:5], won=False)
        self.run_aggregate()
        self.assertEqual(self.alice.unique_conducts, 3)
        self.assertEqual(self.bob.unique_conducts, 4)
        self.assertEqual(self.carol.unique_conducts, 0)
        # the union of the members' ascensions: c[0:6], not 3 + 4 or 7
        self.assertEqual(self.clan.unique_conducts, 6)

    def test_all_conducts_trophy_needs_every_conduct_in_ascensions(self):
        c = self.conducts
        self.game(self.alice, c[:-1])
        self.game(self.alice, c[-1:], won=False)
        self.run_aggregate()
        self.assertEqual(self.alice.unique_conducts, len(c) - 1)
        self.assertFalse(
            self.alice.trophies.filter(name='All Conducts').exists())
        self.game(self.alice, c[-1:])
        self.run_aggregate()
        self.assertTrue(
            self.alice.trophies.filter(name='All Conducts').exists())
        self.assertTrue(
            self.clan.trophies.filter(name='All Conducts').exists())

    def test_latest_start_is_by_start_time_not_end_time(self):
        t = datetime.fromtimestamp(in_window(days=10), timezone.utc)
        # alice's first ascension started first but ended last
        self.game(self.alice, [], start=t, length=timedelta(days=2))
        late = self.game(self.alice, [], start=t + timedelta(hours=2))
        # a death started later than both does not count
        self.game(self.alice, [], won=False, start=t + timedelta(hours=5))
        # bob's started before alice's latest but ended after it
        bobs = self.game(self.bob, [], start=t + timedelta(hours=1),
                         length=timedelta(days=3))
        self.game(self.carol, [], won=False, start=t + timedelta(hours=9))
        self.run_aggregate()
        self.assertEqual(self.alice.latest_start_asc, late)
        self.assertEqual(self.bob.latest_start_asc, bobs)
        self.assertIsNone(self.carol.latest_start_asc)
        self.assertEqual(self.clan.latest_start_asc, late)


class TrophyDefsTests(TestCase):
    # The trophies in trophy_defs only work if the fixtures agree with them,
    # and a resync of the achievements with the game can break that quietly.
    fixtures = ['achievements', 'trophies']

    def test_every_trophy_is_in_the_fixture(self):
        names = set(Trophy.objects.values_list('name', flat=True))
        for name in list(feature_trophies) + list(achievement_count_trophies):
            self.assertIn(name, names)

    def test_every_feature_achievement_is_in_the_fixture(self):
        defines = set(Achievement.objects.values_list('define', flat=True))
        for name, define in feature_trophies.items():
            self.assertIn(define, defines, name)

    def test_count_trophies_are_short_of_all_achievements(self):
        total = Achievement.objects.count()
        for name, count in achievement_count_trophies.items():
            self.assertLess(count, total, name)


class FakeResponse:
    def __init__(self, status_code, content=b''):
        self.status_code = status_code
        self.content = content


class DonorTests(TestCase):
    US = 'https://us.example.org/donors'
    EU = 'https://eu.example.org/donors'

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.xlog_dir = Path(tmp.name)
        for name, value in [('XLOG_DIR', tmp.name),
                            ('DONOR_FILES', [self.US, self.EU])]:
            patcher = mock.patch.object(tnnt.settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.alice = Player.objects.create(name='alice')
        self.bob = Player.objects.create(name='bob', donations=7)
        self.carol = Player.objects.create(name='carol')

    def populate(self, responses):
        # responses: url -> FakeResponse or exception to raise
        def fake_get(url, **kwargs):
            r = responses[url]
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(aggregate.requests, 'get',
                               side_effect=fake_get):
            aggregate.populateDonors()
        for p in (self.alice, self.bob, self.carol):
            p.refresh_from_db()

    def test_counts_lines_and_ignores_unknown_donors(self):
        with self.assertLogs(level='WARNING') as logs:
            self.populate({
                self.US: FakeResponse(200, b'alice\nalice\nbob\nnobody\n\n'),
                self.EU: FakeResponse(200, b'carol\n'),
            })
        self.assertEqual((self.alice.donations, self.bob.donations,
                          self.carol.donations), (2, 1, 1))
        self.assertTrue(any('nonexistent donor nobody' in m
                            for m in logs.output))
        # each fetched file was saved for later fallback
        self.assertEqual((self.xlog_dir / 'donors.eu.example.org')
                         .read_bytes(), b'carol\n')

    def test_previous_credits_are_recomputed_not_accumulated(self):
        self.populate({self.US: FakeResponse(200, b'alice\n'),
                       self.EU: FakeResponse(200, b'')})
        self.assertEqual(self.bob.donations, 0)
        self.assertEqual(self.alice.donations, 1)

    def test_fetch_failure_falls_back_to_saved_copy(self):
        (self.xlog_dir / 'donors.eu.example.org').write_bytes(
            b'carol\ncarol\n')
        with self.assertLogs(level='WARNING') as logs:
            self.populate({
                self.US: FakeResponse(200, b'alice\n'),
                self.EU: requests.ConnectionError('eu is down'),
            })
        self.assertEqual((self.alice.donations, self.carol.donations), (1, 2))
        self.assertTrue(any('last good copy' in m for m in logs.output))

    def test_fetch_failure_without_saved_copy_still_counts_the_rest(self):
        with self.assertLogs(level='ERROR'):
            self.populate({
                self.US: FakeResponse(200, b'alice\n'),
                self.EU: FakeResponse(500),
            })
        self.assertEqual((self.alice.donations, self.carol.donations), (1, 0))


class TempAchievementTests(TestCase):
    fixtures = ['achievements']

    def setUp(self):
        aggregate.load_static_data()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tach_dir = Path(tmp.name)
        patcher = mock.patch.object(tnnt.settings, 'TEMP_ACHIEVEMENTS_PATH',
                                    tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.alice = Player.objects.create(name='alice')
        self.bob = Player.objects.create(name='bob')
        self.carol = Player.objects.create(name='carol')
        # achievements from the first and the last xlog field, so a file
        # can be built that sets exactly one of them, and the last line of
        # the file is read too
        achs = aggregate.ALL_ACHIEVEMENTS
        self.ach_a = achs[0]
        self.ach_b = max(achs, key=lambda a: (
            int(a.xlogfield[len('tnntachieve'):]), a.bit))

    def lines_for(self, *achs):
        lines = ['0x0'] * aggregate.UNIQ_ACHFIELDS
        for ach in achs:
            idx = int(ach.xlogfield[len('tnntachieve'):])
            lines[idx] = hex(int(lines[idx], 16) | (1 << ach.bit))
        return lines

    def write(self, fname, lines):
        (self.tach_dir / fname).write_text('\n'.join(lines) + '\n')

    def test_valid_file_applies_and_malformed_files_are_skipped(self):
        good = self.lines_for(self.ach_a)
        self.write('alice.tach.txt', good)
        self.write('bob.tach.eu.txt', good[:3])                # truncated
        self.write('carol.tach.us.txt', ['zz'] + good[1:])     # not hex
        self.write('dave.tach.txt', good)                      # no Player
        self.write('aggregate.log', ['not a tach file'])
        with self.assertLogs(level='WARNING') as logs:
            aggregate.obtainTempAchievements()
        self.assertEqual(list(self.alice.temp_achievements.all()),
                         [self.ach_a])
        self.assertEqual(self.bob.temp_achievements.count(), 0)
        self.assertEqual(self.carol.temp_achievements.count(), 0)
        self.assertEqual(len([m for m in logs.output if 'Skipping' in m
                              or 'malformed' in m]), 2)

    def test_files_from_several_servers_are_additive(self):
        self.write('alice.tach.us.txt', self.lines_for(self.ach_a))
        self.write('alice.tach.eu.txt', self.lines_for(self.ach_b))
        aggregate.obtainTempAchievements()
        self.assertEqual(set(self.alice.temp_achievements.all()),
                         {self.ach_a, self.ach_b})

    def test_stale_achievements_are_cleared(self):
        self.alice.temp_achievements.add(self.ach_a)
        aggregate.obtainTempAchievements()
        self.assertEqual(self.alice.temp_achievements.count(), 0)

    def test_missing_directory_is_an_error_not_a_crash(self):
        with mock.patch.object(tnnt.settings, 'TEMP_ACHIEVEMENTS_PATH',
                               str(self.tach_dir / 'gone')), \
                self.assertLogs(level='ERROR'):
            aggregate.obtainTempAchievements()


class HandleTests(TestCase):
    fixtures = ['conducts', 'achievements', 'sources', 'trophies']

    def test_full_run_on_fixtures_only(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(tnnt.settings, 'DONOR_FILES', []), \
                mock.patch.object(tnnt.settings, 'TEMP_ACHIEVEMENTS_PATH',
                                  tmp.name):
            aggregate.Command().handle()
        self.assertEqual(aggregate.TOTAL_CONDUCTS, 35)
