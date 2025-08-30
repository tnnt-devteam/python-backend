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

    # Use normalized_death field - already normalized and rejected deaths are NULL
    # Group by normalized_death to avoid duplicates from the start

    # Subquery to find the earliest game for each normalized death
    subq = Game.objects.filter(normalized_death__isnull=False) \
                       .values('normalized_death') \
                       .annotate(earliest=Min('endtime')) \
                       .filter(normalized_death=OuterRef('normalized_death'))

    # Get unique normalized deaths with statistics
    deathdetails = Game.objects.filter(normalized_death__isnull=False) \
                               .values('normalized_death') \
                               .annotate(
        death=F('normalized_death'),  # Rename for compatibility
        time=Subquery(subq.values('earliest')),
        earliest_plr=Subquery(
            Game.objects.filter(normalized_death=OuterRef('normalized_death'))
                       .order_by('endtime')
                       .values('player__name')[:1]
        ),
        nclans = Count('player__clan__name', distinct=True),
        nplayers = Count('player__name', distinct=True)
    ).order_by('normalized_death')

    # Convert to list and return
    return list(deathdetails)
