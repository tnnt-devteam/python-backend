"""
Player.get_streaks(): the first game started after a win is the candidate
for continuing a streak. A game in which the starting character was
rerolled (rerolls > 0) never continues one: as a candidate it kills the
streak, even if it won, and a rerolled win starts a new streak.
"""
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase

import tnnt.settings
from scoreboard.management.commands.pollxlogs import ADDED, import_from_file
from scoreboard.models import Game, Player, Source
from scoreboard.tests.helpers import ACHIEVE_ASCENDED, in_window, xlog_line


class GetStreaksTests(TestCase):
    fixtures = ['sources']

    def setUp(self):
        self.src = Source.objects.get(server='hdf')
        self.player = Player.objects.create(name='alice')

    def game(self, start, length=1, won=True, rerolls=0):
        """A game starting `start` hours into the tournament."""
        begin = tnnt.settings.TOURNAMENT_START + timedelta(hours=start)
        return Game.objects.create(
            version='5.0.0', role='Val', turns=20000, starttime=begin,
            endtime=begin + timedelta(hours=length),
            death='ascended' if won else 'killed by a jackal', won=won,
            rerolls=rerolls, player=self.player, source=self.src)

    def streaks(self):
        return [([g.id for g in s.games], s.continuable)
                for s in self.player.get_streaks()]

    def test_consecutive_wins_make_a_streak(self):
        a = self.game(0)
        b = self.game(2)
        self.assertEqual(self.streaks(), [([a.id, b.id], True)])

    def test_loss_kills_the_streak(self):
        a = self.game(0)
        b = self.game(2)
        self.game(4, won=False)
        self.game(6)
        self.assertEqual(self.streaks(), [([a.id, b.id], False)])

    def test_rerolled_win_kills_the_streak_and_starts_a_new_one(self):
        a = self.game(0)
        b = self.game(2)
        c = self.game(4, rerolls=1)
        d = self.game(6)
        self.assertEqual(self.streaks(),
                         [([a.id, b.id], False), ([c.id, d.id], True)])

    def test_rerolled_win_after_a_single_win_starts_the_streak(self):
        # the first win's "streak" dies at one game and is not listed
        self.game(0)
        b = self.game(2, rerolls=5)
        c = self.game(4)
        self.assertEqual(self.streaks(), [([b.id, c.id], True)])

    def test_rerolled_loss_kills_the_streak(self):
        a = self.game(0)
        b = self.game(2)
        self.game(4, won=False, rerolls=1)
        self.assertEqual(self.streaks(), [([a.id, b.id], False)])

    def test_win_after_a_rerolled_win_continues_its_streak(self):
        # only the rerolled game itself can't continue a streak
        a = self.game(0, rerolls=2)
        b = self.game(2)
        c = self.game(4)
        self.assertEqual(self.streaks(), [([a.id, b.id, c.id], True)])

    def test_rerolled_game_that_is_not_the_candidate_changes_nothing(self):
        # started while the streak's last win was still being played, on
        # another server, so it is not that streak's candidate
        a = self.game(0, length=3)
        self.game(1, won=False, rerolls=1)
        c = self.game(4)
        self.assertEqual(self.streaks(), [([a.id, c.id], True)])

    def test_rerolled_win_kills_every_streak_it_is_candidate_for(self):
        # b is not a's candidate (it started during a), so it starts a
        # second streak; the rerolled d is the candidate for both
        a = self.game(0, length=2)
        b = self.game(1, length=2)
        c = self.game(4)
        d = self.game(6, rerolls=1)
        e = self.game(8)
        # c continues the older streak only
        self.assertEqual(self.streaks(), [([a.id, c.id], False),
                                          ([d.id, e.id], True)])
        self.assertNotIn(b.id, [g for s, _ in self.streaks() for g in s])


class RerollStreakImportTests(TestCase):
    """The same rule, from xlog records through pollxlogs."""
    fixtures = ['conducts', 'achievements', 'sources']

    def test_option_on_without_a_reroll_keeps_the_streak(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / 'hdf.tnnt.xlog'
        won = {'achieve': hex(ACHIEVE_ASCENDED), 'death': 'ascended'}
        # flags bit 3 = the reroll option was on
        path.write_text(
            xlog_line(start=in_window(1), **won)
            + xlog_line(start=in_window(2), flags='0x8', rerolls='0', **won)
            + xlog_line(start=in_window(3), flags='0x8', rerolls='4', **won)
            + xlog_line(start=in_window(4), **won))
        counts = import_from_file(path, Source.objects.get(server='hdf'))
        self.assertEqual(counts[ADDED], 4)
        games = list(Game.objects.order_by('starttime'))
        streaks = Player.objects.get(name='alice').get_streaks()
        self.assertEqual([[g.id for g in s.games] for s in streaks],
                         [[games[0].id, games[1].id],
                          [games[2].id, games[3].id]])
        self.assertEqual([s.continuable for s in streaks], [False, True])
