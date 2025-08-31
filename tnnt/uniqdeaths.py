from tnnt.settings import UNIQUE_DEATH_REJECTIONS, UNIQUE_DEATH_NORMALIZATIONS
from django.db.models import Count, Min, Subquery, OuterRef, F
from scoreboard.models import Game
import logging
import re

logger = logging.getLogger() # use root logger

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
        gameQS.exclude(normalized_death__isnull=True) \
              .values_list('normalized_death', flat=True) \
              .distinct()
    # Return as a set (already normalized and rejected deaths are already filtered)
    return set(normalized_deaths)

def get_unique_death_details():
    # For the Unique Deaths page. Goes more in-depth than just a list of unique
    # deaths for a player or clan.
    # Returns a list of dictionaries containing the death reason, name of the
    # earliest player who got that death, datetime they got that death, and the
    # total number of clans and players who have that death. The list is sorted
    # by death reason.

    # First, produce a QuerySet which maps each distinct normalized death to the
    # number of clans and players that have it and the earliest endtime.
    death_stats = Game.objects.filter(normalized_death__isnull=False) \
                              .values('normalized_death') \
                              .annotate(
        nclans = Count('player__clan__name', distinct=True),
        nplayers = Count('player__name', distinct=True),
        earliest_time = Min('endtime')
    ).order_by('normalized_death')

    # Resolve this to a list so the database only gets hit once
    death_stats = list(death_stats)

    if len(death_stats) <= 0:
        # no games (which qualify for unique deaths) have happened yet
        return []

    # Iterate through all games and build a dictionary that maps each normalized
    # death to a tuple of the earliest time it occurred.
    # TODO: what happens if two games tie for earliest time?
    earliest_players = {}
    games = Game.objects.filter(normalized_death__isnull=False) \
                        .select_related('player') \
                        .values('normalized_death', 'endtime', 'player__name')
    for game in games:
        death = game['normalized_death']
        if death not in earliest_players or game['endtime'] < earliest_players[death][0]:
            earliest_players[death] = (game['endtime'], game['player__name'])

    # Build final output
    output = []
    for stat in death_stats:
        death = stat['normalized_death']
        if not death in earliest_players:
            # huh?
            logger.error("Death %s has no player that accomplished it", death);
        elif earliest_players[death][0] == stat['earliest_time']:
            output.append({
                'death': death,
                'time': stat['earliest_time'],
                'earliest_plr': earliest_players[death][1],
                'nclans': stat['nclans'],
                'nplayers': stat['nplayers']
            })

    return output
