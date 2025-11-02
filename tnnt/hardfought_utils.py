from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from scoreboard.models import Player
from .settings import DGL_DATABASE_PATH, TOURNAMENT_START, TOURNAMENT_END
import sqlite3
from passlib.context import CryptContext
from datetime import datetime
import subprocess
import json
import logging

logger = logging.getLogger(__name__)  # use module-specific logger

# CryptContext to handle multiple password hash formats
# Supports both old dgamelaunch hashes (DES, MD5, bcrypt) and new (sha512_crypt)
pwd_context = CryptContext(
    schemes=["sha512_crypt", "sha256_crypt", "bcrypt", "md5_crypt", "des_crypt"],
    deprecated="auto"
)

def get_dgl_cursor():
    # open in read-only mode
    dgl_conn = sqlite3.connect('file:' + DGL_DATABASE_PATH + '?mode=ro', uri=True)
    dgl_conn.row_factory = sqlite3.Row
    return dgl_conn.cursor()

def get_ip_cursor():
    """Get cursor for dgamelaunch IP tracking database (read-only)"""
    ip_db_path = DGL_DATABASE_PATH.replace('dgamelaunch.db', 'dgamelaunch_ip.db')
    ip_conn = sqlite3.connect('file:' + ip_db_path + '?mode=ro', uri=True)
    ip_conn.row_factory = sqlite3.Row
    return ip_conn.cursor()

def query_remote_ip_db(server, query, params=None):
    """
    Query IP database on a remote server via SSH.
    Args:
        server: 'eu' or 'au' (or 'us' for local, though local uses direct sqlite)
        query: SQL query string
        params: Optional tuple of query parameters
    Returns:
        List of dicts with query results
    """
    if server not in ['eu', 'au', 'us']:
        logger.error('Invalid server: %s', server)
        return []

    # For US server, use local database
    if server == 'us':
        try:
            cursor = get_ip_cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error('Error querying local IP database: %s', str(e))
            return []

    # For remote servers, use SSH
    try:
        db_path = '/opt/nethack/chroot/dgldir/dgamelaunch_ip.db'

        # Build SSH command with sqlite3
        # Use .mode json for easy parsing
        sqlite_cmd = f'sqlite3 -json {db_path} "{query}"'

        # Replace query parameters (sqlite3 CLI doesn't support parameterized queries)
        if params:
            # Escape parameters for SQL injection safety
            escaped_params = [str(p).replace("'", "''") for p in params]
            # Replace ? with actual values
            for param in escaped_params:
                query = query.replace('?', f"'{param}'", 1)
            sqlite_cmd = f'sqlite3 -json {db_path} "{query}"'

        ssh_command = [
            'ssh',
            '-o', 'ConnectTimeout=10',
            '-o', 'BatchMode=yes',
            f'nhsync@{server}.hardfought.org',
            sqlite_cmd
        ]

        result = subprocess.run(
            ssh_command,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            logger.error('SSH query to %s failed: %s', server, result.stderr)
            return []

        # Parse JSON output
        if result.stdout.strip():
            return json.loads(result.stdout)
        return []

    except subprocess.TimeoutExpired:
        logger.error('SSH query to %s timed out', server)
        return []
    except json.JSONDecodeError as e:
        logger.error('Failed to parse JSON from %s: %s', server, str(e))
        return []
    except Exception as e:
        logger.error('Error querying %s IP database: %s', server, str(e))
        return []

def get_multi_account_ips():
    """
    Get list of IP addresses with 2+ accounts that connected during tournament.
    Queries all three servers (US, EU, AU) and merges results.
    Returns list of dicts with: ip_address, account_count, usernames, last_seen, servers
    """
    try:
        # Convert tournament dates to Unix timestamps
        tournament_start_ts = int(TOURNAMENT_START.timestamp())
        tournament_end_ts = int(TOURNAMENT_END.timestamp())

        # Query all three servers
        query = """
            SELECT username, ip_address, last_seen
            FROM user_ip_history
            WHERE last_seen >= {start} AND last_seen < {end}
            ORDER BY ip_address, username
        """.format(start=tournament_start_ts, end=tournament_end_ts)

        all_rows = []
        servers = ['us', 'eu', 'au']

        for server in servers:
            logger.info('Querying %s server for multi-account IPs', server)
            rows = query_remote_ip_db(server, query)
            for row in rows:
                row['server'] = server
            all_rows.extend(rows)
            logger.info('Got %d records from %s', len(rows), server)

        # Group by IP address and username to find unique user-IP pairs
        ip_groups = {}
        for row in all_rows:
            ip = row['ip_address']
            username = row['username']
            server = row['server']

            if ip not in ip_groups:
                ip_groups[ip] = {
                    'usernames': set(),
                    'last_seen': row['last_seen'],
                    'servers': set()
                }

            ip_groups[ip]['usernames'].add(username)
            ip_groups[ip]['servers'].add(server)

            # Keep most recent last_seen
            if row['last_seen'] > ip_groups[ip]['last_seen']:
                ip_groups[ip]['last_seen'] = row['last_seen']

        # Filter to only IPs with 2+ different accounts
        multi_accounts = []
        for ip, data in ip_groups.items():
            if len(data['usernames']) >= 2:
                usernames_sorted = sorted(list(data['usernames']))

                # Get clan information for each username
                from scoreboard.models import Player
                clans = []
                for username in usernames_sorted:
                    try:
                        player = Player.objects.select_related('clan').get(name=username)
                        clan_name = player.clan.name if player.clan else 'None'
                        clans.append(clan_name)
                    except Player.DoesNotExist:
                        clans.append('None')

                multi_accounts.append({
                    'ip_address': ip,
                    'account_count': len(data['usernames']),
                    'usernames': usernames_sorted,
                    'clans': clans,
                    'servers': ', '.join(sorted([s.upper() for s in data['servers']])),
                    'last_seen': datetime.fromtimestamp(
                        data['last_seen']
                    ).strftime('%Y-%m-%d %H:%M')
                })

        # Sort by account count (descending), then by IP
        multi_accounts.sort(key=lambda x: (-x['account_count'], x['ip_address']))

        logger.info('Found %d IPs with multiple accounts', len(multi_accounts))
        return multi_accounts

    except Exception as e:
        logger.error('Error in get_multi_account_ips: %s', str(e))
        return []

def get_player_last_ip(username):
    """
    Get most recent IP address for a player across all servers.
    Checks US, EU, and AU servers and returns the most recent IP.
    """
    try:
        # Query to get most recent IP for this user
        query = """
            SELECT ip_address, last_seen
            FROM user_ip_history
            WHERE username = '{user}'
            ORDER BY last_seen DESC
            LIMIT 1
        """.format(user=username.replace("'", "''"))

        most_recent_ip = None
        most_recent_time = 0

        # Check all three servers
        for server in ['us', 'eu', 'au']:
            rows = query_remote_ip_db(server, query)
            if rows and len(rows) > 0:
                row = rows[0]
                if row['last_seen'] > most_recent_time:
                    most_recent_time = row['last_seen']
                    most_recent_ip = row['ip_address']

        return most_recent_ip

    except Exception as e:
        logger.error('Error getting IP for user %s: %s', username, str(e))
        return None

# Function that looks up a player in first the Player table, then if not found
# there then in dgamelaunch database. If found in dgamelaunch, create the player
# in the Player table and return
def find_player(findname):
    try:
        return Player.objects.get(name=findname)
    except Player.DoesNotExist as e:
        try:
            dgl_curs = get_dgl_cursor()
            uname = dgl_curs.execute('SELECT username FROM dglusers WHERE username = ?',
                                     (findname,)).fetchone()
        except sqlite3.Error as sqlite_e:
            logger.error('ERROR connecting to or executing SQL on sqlite database (get username)')
            logger.error('  db path:', DGL_DATABASE_PATH)
            logger.error('  username:', username)
        if uname is None:
            # not found in dgl, doesn't apparently exist
            logger.info("find_player attempted but '%s' doesn't exist either in dgl db or backend db",
                        findname)
            raise e
        else:
            player = Player(name=findname, clan=None, clan_admin=False)
            player.save()
            logger.info('find_player made new TNNT player "%s" who already existed in dgl db',
                        findname)
            return player

class HdfAuthBackend(BaseBackend):

    def authenticate(self, request, username=None, password=None):
        logger.info('Attempting to authenticate username %s', username)
        try:
            dgl_curs = get_dgl_cursor()
            # get hashed salted password from dgl
            pwd_hash = dgl_curs.execute('SELECT password FROM dglusers WHERE username = ?', (username,)).fetchone()
        except sqlite3.Error as e:
            logger.error('ERROR connecting to or executing SQL on sqlite database (get password)')
            logger.error('  db path: %s', DGL_DATABASE_PATH)
            logger.error('  username: %s', username)
            return None
        if pwd_hash is None:
            logger.info("%s tried to log in but doesn't exist in dgl db", username)
            # doesn't exist in dgl, can't join site
            return None
        else:
            # convert from tuple containing 1 string to just the string
            pwd_hash = pwd_hash[0]
        # compare it against submitted password with passlib
        # pwd_context supports both old (DES, MD5, bcrypt) and new (sha512_crypt) formats
        try:
            if not pwd_context.verify(password, pwd_hash):
                logger.info('%s tried to login but failed due to bad password',
                            username)
                return None
        except ValueError as e:
            logger.error('%s has invalid/unsupported password hash format in dgl database: %s',
                        username, str(e))
            return None

        # success! this is the correct dgl password. look up the user or create
        # if doesn't exist (TNNT login and registration are one and the same)
        logger.info('%s authenticated against dgl password', username)
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            user = User(username=username)
            user.is_staff = False
            user.is_superuser = False
            user.save()
            logger.info('saved new User with name = %s', username)
            player = find_player(username)
            # link to the User record
            player.user = user
            player.save()
            logger.info('linked new User to its Player with name = %s', username)
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
