import warnings

from django.test import TestCase
from django.utils import timezone

from scoreboard.models import Achievement, Player, Source
from scoreboard.tests.test_aggregate import make_game
from tnnt import settings


class PlayerApiTests(TestCase):
    fixtures = ['achievements', 'sources']

    def setUp(self):
        self.src = Source.objects.get(server='hdf')
        self.alice = Player.objects.create(name='alice', total_games=3)

    def test_unique_deaths_has_no_null_entries(self):
        make_game(self.alice, self.src, death='ascended')
        g = make_game(self.alice, self.src, won=False, mines_soko=False,
                      death='killed by a newt')
        g.normalized_death = 'killed by a newt'
        g.save()
        make_game(self.alice, self.src, won=False, mines_soko=False,
                  death='quit', turns=3)
        resp = self.client.get('/api/players/alice/unique_deaths/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {'count': 1, 'deaths': ['killed by a newt']})

    def test_recent_events_uses_aware_datetimes(self):
        g = make_game(self.alice, self.src)
        g.endtime = timezone.now()
        g.save()
        g.achievements.add(Achievement.objects.first())
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            resp = self.client.get('/api/recent-events/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['achievements'][0]['player'], 'alice')

    def test_scoreboard_names_the_tournament_year(self):
        resp = self.client.get('/api/scoreboard/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['tournament'],
                         'TNNT %d' % settings.TOURNAMENT_START.year)
        self.assertEqual(resp.json()['players'][0]['name'], 'alice')
