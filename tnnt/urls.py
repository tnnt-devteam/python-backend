from django.urls import include, path
from rest_framework.routers import DefaultRouter
from tnnt import views as tnntviews
from scoreboard.api_views import (
    PlayerViewSet, ClanViewSet, LeaderboardView,
    RecentEventsView, ScoreboardView
)

# Create router for API viewsets
router = DefaultRouter()
router.register('players', PlayerViewSet)
router.register('clans', ClanViewSet)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('', tnntviews.HomepageView.as_view(), name='root'),
    path('leaderboards', tnntviews.LeaderboardsView.as_view(), name='leaderboards'),
    path('trophies', tnntviews.TrophiesView.as_view(), name='trophies'),
    path('clans', tnntviews.ClansView.as_view(), name='clans'),
    path('players', tnntviews.PlayersView.as_view(), name='players'),
    path('player/<str:playername>', tnntviews.SinglePlayerOrClanView.as_view(), name='singleplayer'),
    path('clan/<str:clanname>', tnntviews.SinglePlayerOrClanView.as_view(), name='singleclan'),
    path('achievements', tnntviews.AchievementsView.as_view(), name='achievements'),
    path('uniquedeaths', tnntviews.UniqueDeathsView.as_view(), name='uniquedeaths'),
    path('ascensions', tnntviews.AscensionsView.as_view(), name='ascensions'),
    path('allgames', tnntviews.AllGamesView.as_view(), name='allgames'),
    path('faq', tnntviews.FaqView.as_view(), name='faq'),
    path('stats', tnntviews.StatsView.as_view(), name='stats'),
    path('archives', tnntviews.ArchivesView.as_view(), name='archives'),
    path('clanmgmt', tnntviews.ClanMgmtView.as_view(), name='clanmgmt'),
    path('', include('django.contrib.auth.urls')),

    # API endpoints
    path('api/', include(router.urls)),
    path('api/leaderboards/', LeaderboardView.as_view(), name='api-leaderboards'),
    path('api/recent-events/', RecentEventsView.as_view(), name='api-recent-events'),
    path('api/scoreboard/', ScoreboardView.as_view(), name='api-scoreboard'),
]

