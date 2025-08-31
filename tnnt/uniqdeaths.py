from tnnt.settings import UNIQUE_DEATH_REJECTIONS, UNIQUE_DEATH_NORMALIZATIONS
from django.db.models import Count, Min, Subquery, OuterRef, F
from scoreboard.models import Game
import re

def normalize(death):
    # Given a death string, apply normalizations from settings.
    for regtuple in UNIQUE_DEATH_NORMALIZATIONS:
        death = re.sub(regtuple[0], regtuple[1], death)
    return death

def reject(death):
    # Given a death string, return True if it should be excluded as a
    # unique death and False if not.
    for regex in UNIQUE_DEATH_REJECTIONS:
        if re.search(regex, death) is not None:
            return True
    return False

def compile_unique_deaths(gameQS):
    # Given a QuerySet of Game objects, return a set containing strings of all
    # the unique deaths from those games after rejections and normalizations are
    # applied.
    # This is primarily for aggregation (but is currently also used to show the
    # unique deaths on a player/clan page) and runs faster than
    # get_unique_death_details() that returns the players who first got a death
    # and when.

    # Use the pre-normalized deaths field for efficiency
    # Filter out NULL values (rejected deaths) and get distinct values
    normalized_deaths = \
        gameQS.exclude(normalized_death__isnull=True).values_list('normalized_death', flat=True).distinct()
    # Return as a set (already normalized and rejected deaths are already filtered)
    return set(normalized_deaths)

def get_unique_death_details():
    # For the Unique Deaths page. Goes more in-depth than just a list of unique
    # deaths for a player or clan.
    # Returns a list of dictionaries containing the death reason, name of the
    # earliest player who got that death, datetime they got that death, and the
    # total number of clans and players who have that death. The list is sorted
    # by death reason.

    # Use normalized_death field for efficiency
    # Get all the stats in batch queries instead of N+1

    # First, get aggregate stats for each normalized death
    death_stats = Game.objects.filter(normalized_death__isnull=False) \
                              .values('normalized_death') \
                              .annotate(
        nclans = Count('player__clan__name', distinct=True),
        nplayers = Count('player__name', distinct=True),
        earliest_time = Min('endtime')
    ).order_by('normalized_death')

    # Build output list, fetching earliest players in batch
    stats_list = list(death_stats)

    # Get all earliest games in one query
    earliest_games = {}
    for stat in stats_list:
        # Collect all the death/time pairs we need to look up
        earliest_games[stat['normalized_death']] = stat['earliest_time']

    # Fetch all earliest players in a single query
    if earliest_games:
        games = Game.objects.filter(
            normalized_death__in=earliest_games.keys()
        ).select_related('player').values('normalized_death', 'endtime', 'player__name')

        # Build a lookup dict for earliest player per death
        earliest_players = {}
        for game in games:
            death = game['normalized_death']
            if death not in earliest_players or game['endtime'] < earliest_players[death][0]:
                earliest_players[death] = (game['endtime'], game['player__name'])

    # Build final output
    output = []
    for stat in stats_list:
        death = stat['normalized_death']
        if death in earliest_players and earliest_players[death][0] == stat['earliest_time']:
            output.append({
                'death': death,
                'time': stat['earliest_time'],
                'earliest_plr': earliest_players[death][1],
                'nclans': stat['nclans'],
                'nplayers': stat['nplayers']
            })

    return output
