from rest_framework import viewsets, views
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import F
from datetime import datetime, timedelta
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from functools import wraps
from scoreboard.models import Player, Clan, Game, Achievement
from .serializers import (
    PlayerListSerializer, PlayerDetailSerializer, ClanSerializer,
    GameSerializer, AchievementSerializer
)


def get_client_ip(request):
    """Return the real client IP.

    In production, Apache reverse-proxies to localhost:8000, so REMOTE_ADDR is
    always 127.0.0.1. Apache (the single trusted proxy) appends the real client
    as the LAST hop of X-Forwarded-For; earlier entries are client-supplied and
    must not be trusted. Direct localhost hits (e.g. the IRC bot) have no XFF
    header and fall back to REMOTE_ADDR.
    """
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'):
    """Rate limit decorator that excludes localhost.

    Throttling always buckets by the real client IP (see get_client_ip); the
    `key` argument is retained for call-site compatibility but superseded.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            # Skip rate limiting for localhost (e.g. the IRC bot hitting
            # localhost:8000 directly, which has no X-Forwarded-For)
            client_ip = get_client_ip(request)
            if client_ip in ['127.0.0.1', '::1', 'localhost']:
                return func(request, *args, **kwargs)
            # Apply rate limiting for other IPs, keyed by real client IP
            return ratelimit(
                key=lambda group, req: get_client_ip(req),
                rate=rate, method=method
            )(func)(request, *args, **kwargs)
        return wrapper
    return decorator


@method_decorator(
    ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'),
    name='list'
)
@method_decorator(
    ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'),
    name='retrieve'
)
class PlayerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (
        Player.objects.filter(total_games__gt=0)
        .select_related('clan')
        .prefetch_related('trophies')
    )
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PlayerDetailSerializer
        return PlayerListSerializer

    @action(detail=True, methods=['get'])
    def recent_games(self, request, name=None):
        player = self.get_object()
        games = (
            Game.objects.filter(player=player)
            .select_related('player')
            .prefetch_related('achievements')
            .order_by('-endtime')[:10]
        )
        serializer = GameSerializer(games, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def achievements(self, request, name=None):
        player = self.get_object()
        achievements = Achievement.objects.filter(
            game__player=player
        ).distinct()
        serializer = AchievementSerializer(achievements, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def unique_deaths(self, request, name=None):
        player = self.get_object()
        deaths = Game.objects.filter(
            player=player,
            death__isnull=False
        ).exclude(
            death__in=['quit', 'escaped']
        ).values_list('normalized_death', flat=True).distinct()
        return Response({'count': deaths.count(), 'deaths': list(deaths)})

    @action(detail=True, methods=['get'])
    def streaks(self, request, name=None):
        player = self.get_object()
        streaks = player.get_streaks()
        streak_data = []
        for streak in streaks:
            streak_data.append({
                'length': len(streak.games),
                'games': [g.id for g in streak.games],
                'active': streak.continuable
            })
        return Response(streak_data)


@method_decorator(
    ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'),
    name='list'
)
@method_decorator(
    ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET'),
    name='retrieve'
)
class ClanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Clan.objects.prefetch_related('player_set', 'trophies')
    serializer_class = ClanSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'


class LeaderboardView(views.APIView):
    @method_decorator(
        ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET')
    )
    def get(self, request):
        player_boards = {
            'most_wins': list(
                Player.objects.filter(wins__gt=0)
                .order_by('-wins', 'name')
                .values('name', 'wins', 'clan__name')[:10]),
            'most_games': list(
                Player.objects.filter(total_games__gt=0)
                .order_by('-total_games', 'name')
                .values('name', 'total_games', 'clan__name')[:10]),
            'highest_score': list(
                Player.objects.filter(max_score_game__isnull=False)
                .annotate(score=F('max_score_game__points'))
                .order_by('-score')
                .values('name', 'score', 'clan__name')[:10]
            ),
        }

        clan_boards = {
            'most_wins': list(
                Clan.objects.filter(wins__gt=0)
                .order_by('-wins', 'name')
                .values('name', 'wins')[:10]),
            'most_games': list(
                Clan.objects.filter(total_games__gt=0)
                .order_by('-total_games', 'name')
                .values('name', 'total_games')[:10]),
        }

        return Response({
            'players': player_boards,
            'clans': clan_boards
        })


class RecentEventsView(views.APIView):
    @method_decorator(
        ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET')
    )
    def get(self, request):
        cutoff = datetime.now() - timedelta(hours=1)

        recent_achievements = Game.objects.filter(
            endtime__gte=cutoff
        ).exclude(
            achievements__isnull=True
        ).select_related('player').prefetch_related('achievements')

        achievements = []
        for game in recent_achievements:
            for achievement in game.achievements.all():
                achievements.append({
                    'player': game.player.name,
                    'achievement': achievement.name,
                    'timestamp': game.endtime
                })

        trophies = []

        return Response({
            'achievements': achievements,
            'trophies': trophies
        })


class ScoreboardView(views.APIView):

    @method_decorator(
        ratelimit_exclude_localhost(key='ip', rate='100/m', method='GET')
    )
    def get(self, request):
        players = (
            Player.objects.filter(total_games__gt=0)
            .order_by('-wins', 'name')
        )
        clans = Clan.objects.all().order_by('-wins', 'name')

        # Return all players and clans
        player_data = PlayerListSerializer(players, many=True).data
        clan_data = ClanSerializer(clans, many=True).data

        last_game = Game.objects.order_by('-endtime').first()
        last_updated = last_game.endtime if last_game else None

        return Response({
            'tournament': f'TNNT {datetime.now().year}',
            'players': player_data,
            'clans': clan_data,
            'last_updated': last_updated
        })
