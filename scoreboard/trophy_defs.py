"""
Static definitions behind the trophies: how many roles/races/etc. NetHack
has, and which role-race-alignment combinations the Great/Lesser Race and
Role trophies require.

Pure data with no Django imports, shared by the aggregate command (which
awards trophies) and tnnt/trophy_grid.py (which shows progress towards
them), so that neither has to import the other.
"""

# These are determined by NetHack and there's no expectation that TNNT would
# ever change them. However, they may need to change if changes are made to
# vanilla NetHack which are then incorporated into TNNT (for instance, if the
# DevTeam adds a new role or race or, more likely, allows a new role-race
# combination).
TOTAL_GENDERS = 2
TOTAL_ALIGNMENTS = 3
TOTAL_RACES = 5
TOTAL_ROLES = 13
# 38 role-race-alignment starting combinations, doubled for gender, minus the
# 3 Valkyrie combinations that are female-only.
TOTAL_POSSIBLE_COMBOS = 73

# Great <Race>: ascend every role the race can be. Lesser <Race>: the same,
# but only requires finishing the Mines and Sokoban.
great_lesser_race = {
    'Dwarf': {'race': 'Dwa', 'req_roles': {'Arc', 'Cav', 'Val'}},
    'Orc': {'race': 'Orc', 'req_roles': {'Bar', 'Ran', 'Rog', 'Wiz'}},
    'Elf': {'race': 'Elf', 'req_roles': {'Pri', 'Ran', 'Wiz'}},
    'Gnome': {'race': 'Gno',
              'req_roles': {'Arc', 'Cav', 'Hea', 'Ran', 'Wiz'}},
    'Human': {'race': 'Hum', 'req_roles': {'Kni', 'Mon', 'Sam', 'Tou'}},
}

# Great <Role>: ascend every race-alignment combination the role allows.
# Roles with a single combination (Knight, Samurai, Tourist) have no trophy.
great_lesser_role = {
    'Archeologist': {
        'role': 'Arc',
        'req_race_algn': {'Dwa-Law', 'Hum-Law', 'Hum-Neu', 'Gno-Neu'},
    },
    'Barbarian': {
        'role': 'Bar',
        'req_race_algn': {'Hum-Neu', 'Hum-Cha', 'Orc-Cha'},
    },
    'Caveperson': {
        'role': 'Cav',
        'req_race_algn': {'Dwa-Law', 'Hum-Law', 'Hum-Neu', 'Gno-Neu'},
    },
    'Healer': {
        'role': 'Hea',
        'req_race_algn': {'Hum-Neu', 'Gno-Neu'},
    },
    'Monk': {
        'role': 'Mon',
        'req_race_algn': {'Hum-Law', 'Hum-Neu', 'Hum-Cha'},
    },
    'Priest': {
        'role': 'Pri',
        'req_race_algn': {'Hum-Law', 'Hum-Neu', 'Hum-Cha', 'Elf-Cha'},
    },
    'Ranger': {
        'role': 'Ran',
        'req_race_algn': {'Hum-Neu', 'Gno-Neu', 'Hum-Cha', 'Elf-Cha',
                          'Orc-Cha'},
    },
    'Rogue': {
        'role': 'Rog',
        'req_race_algn': {'Hum-Cha', 'Orc-Cha'},
    },
    'Valkyrie': {
        'role': 'Val',
        'req_race_algn': {'Dwa-Law', 'Hum-Law', 'Hum-Neu'},
    },
    'Wizard': {
        'role': 'Wiz',
        'req_race_algn': {'Hum-Neu', 'Gno-Neu', 'Hum-Cha', 'Elf-Cha',
                          'Orc-Cha'},
    },
}
