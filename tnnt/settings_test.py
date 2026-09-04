"""
Test settings: SQLite in-memory database, console-only logging, no rate
limiting. Never imported by production.

The MariaDB user only has privileges on the scoreboard database, so
Django's test runner cannot create a test database there. Run the suite
with:

    DJANGO_SETTINGS_MODULE=tnnt.settings_test ./manage.py test scoreboard

Only settings that Django itself reads can be overridden here. The
application code reads tournament settings (TOURNAMENT_START, XLOG_DIR,
TEMP_ACHIEVEMENTS_PATH, DONOR_FILES, ...) straight from the tnnt.settings
module, so tests patch attributes of that module with unittest.mock
instead of redefining them here.
"""
import os

# settings.py reads these with os.environ[...]; a test run must not need
# secrets.sh to be sourced.
os.environ.setdefault('SECRET_KEY', 'test-only-secret-key')
os.environ.setdefault('DATABASE_PASSWORD', 'unused-under-sqlite')

from .settings import *  # noqa: E402,F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Never open the production log file from a test run. Only errors reach the
# console; tests that expect warnings capture them with assertLogs().
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'ERROR',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
}

# django-ratelimit honours this flag; throttling would make view tests
# depend on how many requests earlier tests made.
RATELIMIT_ENABLE = False
