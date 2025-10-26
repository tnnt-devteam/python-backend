from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.models import User
from scoreboard.models import Player
from .settings import DGL_DATABASE_PATH
import sqlite3
from passlib.context import CryptContext
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
