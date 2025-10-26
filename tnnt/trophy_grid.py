"""
Trophy Progress Tracker Grid Generator

This module generates data structures for displaying a player's or clan's
progress toward various trophies in a grid format, showing which role-race-
alignment combinations have been completed.

The grid format was designed by ais523 and other TNNT community members.
"""

from django.db.models import Q, Count
from django.core.cache import cache
from scoreboard.models import Game

# Cache timeout: 10 minutes (600 seconds)
# Grid data is invalidated when new games are aggregated
TROPHY_GRID_CACHE_TIMEOUT = 600

# Define all valid role-race-alignment starting combinations in NetHack
# This matches the combinations used in aggregate.py for trophy calculations
VALID_COMBOS = {
    # Format: (role, race, align)
    # Archeologist
    ('Arc', 'Dwa', 'Law'),
    ('Arc', 'Hum', 'Law'),
    ('Arc', 'Hum', 'Neu'),
    ('Arc', 'Gno', 'Neu'),

    # Barbarian
    ('Bar', 'Hum', 'Neu'),
    ('Bar', 'Hum', 'Cha'),
    ('Bar', 'Orc', 'Cha'),

    # Caveperson
    ('Cav', 'Dwa', 'Law'),
    ('Cav', 'Hum', 'Law'),
    ('Cav', 'Hum', 'Neu'),
    ('Cav', 'Gno', 'Neu'),

    # Healer
    ('Hea', 'Hum', 'Neu'),
    ('Hea', 'Gno', 'Neu'),

    # Knight
    ('Kni', 'Hum', 'Law'),

    # Monk
    ('Mon', 'Hum', 'Law'),
    ('Mon', 'Hum', 'Neu'),
    ('Mon', 'Hum', 'Cha'),

    # Priest
    ('Pri', 'Hum', 'Law'),
    ('Pri', 'Hum', 'Neu'),
    ('Pri', 'Hum', 'Cha'),
    ('Pri', 'Elf', 'Cha'),

    # Ranger
    ('Ran', 'Hum', 'Neu'),
    ('Ran', 'Gno', 'Neu'),
    ('Ran', 'Hum', 'Cha'),
    ('Ran', 'Elf', 'Cha'),
    ('Ran', 'Orc', 'Cha'),

    # Rogue
    ('Rog', 'Hum', 'Cha'),
    ('Rog', 'Orc', 'Cha'),

    # Samurai
    ('Sam', 'Hum', 'Law'),

    # Tourist
    ('Tou', 'Hum', 'Neu'),

    # Valkyrie
    ('Val', 'Dwa', 'Law'),
    ('Val', 'Hum', 'Law'),
    ('Val', 'Hum', 'Neu'),

    # Wizard
    ('Wiz', 'Hum', 'Neu'),
    ('Wiz', 'Gno', 'Neu'),
    ('Wiz', 'Hum', 'Cha'),
    ('Wiz', 'Elf', 'Cha'),
    ('Wiz', 'Orc', 'Cha'),
}

# Define the order of roles and race-alignment combinations for display
ROLES_ORDER = [
    'Arc', 'Bar', 'Cav', 'Hea', 'Kni', 'Mon', 'Pri',
    'Ran', 'Rog', 'Sam', 'Tou', 'Val', 'Wiz'
]
RACE_ALIGN_ORDER = [
    'Hum-Law',
    'Dwa-Law',
    'Hum-Neu',
    'Gno-Neu',
    'Hum-Cha',
    'Elf-Cha',
    'Orc-Cha',
]

def generate_combo_grid_data(player_or_clan, use_cache=True):
    """
    Generate trophy progress grid data for a player or clan.

    Args:
        player_or_clan: A Player or Clan model instance
        use_cache: Whether to use cached data (default True)

    Returns:
        dict: A dictionary containing:
            - 'rows': List of row data (race-align combos)
            - 'roles': List of role names in display order
            - 'trophy_status': Dict showing which trophies are achieved
    """
    # Determine if this is a player or clan by checking model class name
    is_clan = player_or_clan.__class__.__name__ == 'Clan'

    # Generate cache key
    cache_prefix = 'clan' if is_clan else 'player'
    cache_key = f'trophy_grid_{cache_prefix}_{player_or_clan.id}'

    # Try to get from cache first
    if use_cache:
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data

    # Cache miss or cache disabled - generate the data
    # Get all games for this player/clan
    if is_clan:
        games_qs = Game.objects.filter(player__clan=player_or_clan)
    else:
        games_qs = Game.objects.filter(player=player_or_clan)

    # Query 1: Get all role-race-align combos with mines_soko completed
    # Group by role, race, align0 and check if any have mines_soko=True
    mines_soko_combos = set()
    for game in games_qs.filter(
            mines_soko=True).values('role', 'race', 'align0'):
        mines_soko_combos.add((game['role'], game['race'], game['align0']))

    # Query 2: Get all role-race-align-gender combos with ascensions
    # Group by role, race, align0, gender0
    ascension_combos = {}
    for game in games_qs.filter(
            won=True).values('role', 'race', 'align0', 'gender0'):
        key = (game['role'], game['race'], game['align0'])
        if key not in ascension_combos:
            ascension_combos[key] = {'male': False, 'female': False}

        if game['gender0'] == 'Mal':
            ascension_combos[key]['male'] = True
        elif game['gender0'] == 'Fem':
            ascension_combos[key]['female'] = True

    # Build the grid data structure
    rows = []
    for race_align in RACE_ALIGN_ORDER:
        race, align = race_align.split('-')

        row_data = {
            'race_align': race_align,
            'combos': []
        }

        for role in ROLES_ORDER:
            combo_key = (role, race, align)
            valid = combo_key in VALID_COMBOS

            combo_data = {
                'role': role,
                'valid': valid,
                'mines_soko': False,
                'asc_male': False,
                'asc_female': False,
            }

            if valid:
                # Check if this combo has mines_soko completed
                combo_data['mines_soko'] = (
                    combo_key in mines_soko_combos
                )

                # Check if this combo has ascensions
                if combo_key in ascension_combos:
                    combo_data['asc_male'] = (
                        ascension_combos[combo_key]['male']
                    )
                    combo_data['asc_female'] = (
                        ascension_combos[combo_key]['female']
                    )

            row_data['combos'].append(combo_data)

        rows.append(row_data)

    # Calculate trophy status based on the data
    trophy_status = _calculate_trophy_status(
        player_or_clan, mines_soko_combos, ascension_combos
    )

    result = {
        'rows': rows,
        'roles': ROLES_ORDER,
        'trophy_status': trophy_status,
    }

    # Store in cache
    if use_cache:
        cache.set(cache_key, result, TROPHY_GRID_CACHE_TIMEOUT)

    return result

def invalidate_trophy_grid_cache(player_or_clan=None):
    """
    Invalidate trophy grid cache for a specific player/clan or all.

    Args:
        player_or_clan: If provided, invalidate only for this
                       player/clan. If None, invalidate all trophy
                       grid caches.
    """
    if player_or_clan is not None:
        # Invalidate cache for specific player or clan
        is_clan = player_or_clan.__class__.__name__ == 'Clan'
        cache_prefix = 'clan' if is_clan else 'player'
        cache_key = f'trophy_grid_{cache_prefix}_{player_or_clan.id}'
        cache.delete(cache_key)
    else:
        # Invalidate all trophy grid caches
        # Try to use delete_pattern if available (Redis), otherwise clear all
        if hasattr(cache, 'delete_pattern'):
            cache.delete_pattern('trophy_grid_*')
        else:
            # LocMemCache and other backends don't support pattern deletion
            # For development/testing, we can just clear the entire cache
            cache.clear()

def _calculate_trophy_status(
        player_or_clan, mines_soko_combos, ascension_combos):
    """
    Calculate which trophies are completed based on combo data.

    This provides a quick summary of trophy progress without querying
    trophies table.
    """
    from scoreboard.management.commands.aggregate import (
        great_lesser_race, great_lesser_role
    )
    from scoreboard.models import Conduct, Achievement

    status = {
        'great_races': {},
        'lesser_races': {},
        'great_roles': {},
        'lesser_roles': {},
        'all_roles': False,
        'all_races': False,
        'nethack_master': False,
        'both_genders': False,
        'all_alignments': False,
        'all_conducts': False,
        'all_achievements': False,
        'nethack_dominator': False,
        'never_scum': False,
        'keep_nemesis_alive': False,
        'keep_vlad_alive': False,
        'keep_rodney_alive': False,
        'keep_high_priest_alive': False,
        'keep_riders_alive': False,
    }

    # Check Great/Lesser Race trophies
    for fullrace, details in great_lesser_race.items():
        race = details['race']
        req_roles = details['req_roles']

        # Great Race: all required roles ascended with this race
        asc_roles = set(
            combo[0] for combo in ascension_combos.keys()
            if combo[1] == race
        )
        status['great_races'][fullrace] = req_roles.issubset(asc_roles)

        # Lesser Race: all required roles with mines_soko for this race
        ms_roles = set(
            combo[0] for combo in mines_soko_combos if combo[1] == race
        )
        status['lesser_races'][fullrace] = req_roles.issubset(ms_roles)

    # Check Great/Lesser Role trophies
    for fullrole, details in great_lesser_role.items():
        role = details['role']
        req_race_algn = details['req_race_algn']

        # Great Role: all required race-align combos ascended with role
        asc_race_align = set(
            f"{combo[1]}-{combo[2]}"
            for combo in ascension_combos.keys()
            if combo[0] == role
        )
        status['great_roles'][fullrole] = (
            req_race_algn.issubset(asc_race_align)
        )

        # Lesser Role: all required race-align combos with mines_soko
        ms_race_align = set(
            f"{combo[1]}-{combo[2]}"
            for combo in mines_soko_combos
            if combo[0] == role
        )
        status['lesser_roles'][fullrole] = (
            req_race_algn.issubset(ms_race_align)
        )

    # Check All Roles and All Races
    asc_roles = set(combo[0] for combo in ascension_combos.keys())
    asc_races = set(combo[1] for combo in ascension_combos.keys())

    status['all_roles'] = len(asc_roles) == 13  # TOTAL_ROLES
    status['all_races'] = len(asc_races) == 5   # TOTAL_RACES

    # Check NetHack Master (all 73 unique ascensions)
    status['nethack_master'] = (
        len(ascension_combos) == 73  # TOTAL_POSSIBLE_COMBOS
    )

    # Determine if this is a player or clan
    is_clan = player_or_clan.__class__.__name__ == 'Clan'

    # Get all games for this player/clan
    if is_clan:
        games_qs = Game.objects.filter(player__clan=player_or_clan)
    else:
        games_qs = Game.objects.filter(player=player_or_clan)

    # Check Both Genders - need at least one male and one female ascension
    genders = set()
    for combo_data in ascension_combos.values():
        if combo_data['male']:
            genders.add('male')
        if combo_data['female']:
            genders.add('female')
    status['both_genders'] = len(genders) == 2

    # Check All Alignments - need ascensions with all 3 alignments
    asc_aligns = set(combo[2] for combo in ascension_combos.keys())
    status['all_alignments'] = len(asc_aligns) == 3  # Law, Neu, Cha

    # Check All Conducts - need all conducts preserved across ascensions
    from scoreboard.models import Conduct, Achievement
    all_conduct_bits = set()
    for game in games_qs.filter(won=True):
        all_conduct_bits.update(game.conducts.all())

    # Track individual conducts
    status['individual_conducts'] = {}
    all_conducts = Conduct.objects.all().order_by('name')
    for conduct in all_conducts:
        status['individual_conducts'][conduct.name] = conduct in all_conduct_bits

    total_conducts = Conduct.objects.count()
    status['all_conducts'] = len(all_conduct_bits) >= total_conducts

    # Check All Achievements - need all achievements across all games
    total_achievements = Achievement.objects.count()
    all_achievement_bits = set()
    for game in games_qs:
        all_achievement_bits.update(game.achievements.all())
    status['all_achievements'] = len(all_achievement_bits) >= total_achievements

    # Check NetHack Dominator - NetHack Master + All Conducts
    status['nethack_dominator'] = (
        status['nethack_master'] and status['all_conducts']
    )

    # Check Never Scum a Game - no games quit/escaped within 100 turns
    scummed_games = games_qs.filter(
        Q(turns__lte=100) & (Q(death='quit') | Q(death='escaped'))
    ).count()
    status['never_scum'] = (games_qs.count() > 0 and scummed_games == 0)

    # Check Keep X Alive trophies - these are conducts in winning games
    # These conducts are earned by NOT killing certain NPCs
    winning_games = games_qs.filter(won=True).prefetch_related('conducts')
    if winning_games.exists():
        # Check if any winning game has the specific conduct
        all_conducts = Conduct.objects.all()
        conduct_map = {c.shortname: c for c in all_conducts}

        # Keep Your Nemesis Alive - conduct shortname 'neme'
        status['keep_nemesis_alive'] = winning_games.filter(
            conducts=conduct_map.get('neme')
        ).exists() if 'neme' in conduct_map else False

        # Keep Vlad Alive - conduct shortname 'vlad'
        status['keep_vlad_alive'] = winning_games.filter(
            conducts=conduct_map.get('vlad')
        ).exists() if 'vlad' in conduct_map else False

        # Keep Rodney Alive - conduct shortname 'wiz'
        status['keep_rodney_alive'] = winning_games.filter(
            conducts=conduct_map.get('wiz')
        ).exists() if 'wiz' in conduct_map else False

        # Keep The High Priest of Moloch Alive - conduct shortname 'prst'
        status['keep_high_priest_alive'] = winning_games.filter(
            conducts=conduct_map.get('prst')
        ).exists() if 'prst' in conduct_map else False

        # Keep The Riders Alive - conduct shortname 'ride'
        status['keep_riders_alive'] = winning_games.filter(
            conducts=conduct_map.get('ride')
        ).exists() if 'ride' in conduct_map else False

    return status
