#!/bin/bash
# test_mode.sh - put tnnt.org into test mode, and back to normal
#
# Usage: ./test_mode.sh on|off|status [--dry-run]
#
#   on         Back up the database, restart the site in DEBUG mode, turn
#              non-admin logins and clan operations on and load the test
#              xlogfiles (./manage.py test_mode on).
#   off        Back up the database, stop the site, delete everything test
#              mode created and put the switches back (./manage.py test_mode
#              off), start the site without DEBUG and restart tnntbot.
#   status     Show which mode the site is in.
#   --dry-run  Run every check and rehearse the database work in a
#              transaction that is rolled back. Changes nothing.
#
# Run it as root. In DEBUG mode tnnt/settings.py checks logins against
# dgamelaunch_test.db: alice, bob, chuck, david, eve, gimli, janet, omghax
# and sally, each with their name as password. Turn test mode off before
# the tournament starts.
#
# While the site is in test mode:
#   - only those nine accounts can log in; the admins cannot
#   - anyone who tries a test account's name as its password gets in; off
#     deletes whatever they create
#   - error pages show tracebacks, and 404 pages list the URLs, to anyone
#   - static files are served straight from tnnt/static, without whitenoise
#     or collectstatic; Cloudflare still caches /static/ for 4 hours
#   - every SQL query goes to /var/log/tnnt/tnnt_server.log
#
# The settings below can be overridden from the environment. That is only
# meant for trying the script on a scratch copy of the site.

set -uo pipefail

REPO=${TNNT_REPO:-/home/build/python-backend}
SERVICE=${TNNT_SERVICE:-tnnt_website.service}
ENV_FILE=${TNNT_ENV_FILE:-/etc/default/tnnt_website}
STATE_DIR=${TNNT_STATE_DIR:-/var/lib/tnnt_test_mode}
LOCAL_URL=${TNNT_LOCAL_URL:-http://127.0.0.1:8000}
PUBLIC_URL=${TNNT_PUBLIC_URL-https://tnnt.org/}     # empty: not checked
BACKUP_DIR=${TNNT_BACKUP_DIR-/root}                 # empty: no backup
BOT_SERVICE=${TNNT_BOT_SERVICE-tnntbot.service}     # empty: no restart
LOCK=${TNNT_LOCK:-/run/lock/tnnt_test_mode.lock}

STATE="$STATE_DIR/state.json"
MARKER='# Added by test_mode.sh, which removes it again: the site is in test mode'
TEST_ACCOUNT=alice
BACKUP_FILE=

step() { printf '\n== %s\n' "$*"; }
ok() { printf '   ok: %s\n' "$*"; }
would() { printf '   dry run, would: %s\n' "$*"; }
warn() { printf '   WARNING: %s\n' "$*" >&2; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    printf 'Usage: %s on|off|status [--dry-run]\n' "$0" >&2
    exit 2
}

# manage.py with the site's virtualenv and secrets. DEBUG is left out on
# purpose: the database work does not need it, and with it every SQL query
# would be logged.
manage() {
    (cd "$REPO" && set +u && source ./secrets.sh \
        && exec env -u DEBUG env/bin/python3 manage.py "$@")
}

manage_debug() {
    (cd "$REPO" && set +u && source ./secrets.sh \
        && DEBUG=True exec env/bin/python3 manage.py "$@")
}

http_code() {
    curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1"
}

site_answers() {
    [ "$(http_code "$LOCAL_URL/")" = 200 ]
}

wait_for_site() {
    local i
    for i in $(seq 1 90); do
        site_answers && return 0
        sleep 1
    done
    return 1
}

# A 404 from Django in DEBUG mode names the URLconf it searched
debug_is_live() {
    curl -s --max-time 10 "$LOCAL_URL/test-mode-probe" | grep -q 'URLconf'
}

env_has_debug() {
    [ -f "$ENV_FILE" ] && grep -qxF "$MARKER" "$ENV_FILE"
}

env_add_debug() {
    printf '%s\nDEBUG=True\n' "$MARKER" >> "$ENV_FILE"
}

# Remove the marker and the DEBUG=True line under it, and the file if
# nothing else is left in it
env_remove_debug() {
    local tmp
    tmp=$(mktemp) || return 1
    if ! awk -v marker="$MARKER" '
            $0 == marker { skip = 1; next }
            skip && $0 == "DEBUG=True" { skip = 0; next }
            { skip = 0; print }' "$ENV_FILE" > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    if grep -q '[^[:space:]]' "$tmp"; then
        cat "$tmp" > "$ENV_FILE"
    else
        rm -f "$ENV_FILE"
    fi
    rm -f "$tmp"
}

restart_site() {
    systemctl restart "$SERVICE" && wait_for_site
}

# Log in as a test player over HTTP, the way a browser does
login_works() {
    local jar token result page
    jar=$(mktemp) || return 1
    curl -s -c "$jar" -o /dev/null --max-time 10 "$LOCAL_URL/login/"
    token=$(awk '$6 == "csrftoken" { print $7 }' "$jar")
    result=$(curl -s -b "$jar" -c "$jar" -o /dev/null --max-time 30 \
        -w '%{http_code} %{redirect_url}' -H "Referer: $LOCAL_URL/login/" \
        --data-urlencode "csrfmiddlewaretoken=$token" \
        --data-urlencode "username=$TEST_ACCOUNT" \
        --data-urlencode "password=$TEST_ACCOUNT" "$LOCAL_URL/login/")
    page=$(curl -s -b "$jar" --max-time 30 "$LOCAL_URL/")
    rm -f "$jar"
    [[ $result == 302* && $result != *logins-disabled* && \
       $result != */login/* ]] && grep -q 'href="/clanmgmt"' <<< "$page"
}

backup_db() {
    local file size tables expected
    file="$BACKUP_DIR/scoreboard-db-backup-$(date +%Y%m%d_%H%M%S).sql.gz"
    mysqldump --single-transaction --routines --triggers scoreboard \
        | gzip > "$file" || die "mysqldump failed; nothing changed"
    size=$(stat -c %s "$file")
    tables=$(zcat "$file" | grep -c '^CREATE TABLE')
    expected=$(mysql -N -e "SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'scoreboard' AND table_type = 'BASE TABLE'")
    if [ "$tables" != "$expected" ] || [ "$size" -lt 1000 ]; then
        die "backup $file looks wrong ($size bytes, $tables of $expected tables); nothing changed"
    fi
    BACKUP_FILE=$file
    ok "$file ($size bytes, $tables tables)"
}

preflight() {
    local mode=$1
    step "Checking ($mode)"
    [ "$(id -u)" = 0 ] || die "run this as root"
    [ -f "$REPO/manage.py" ] && [ -x "$REPO/env/bin/python3" ] \
        && [ -f "$REPO/secrets.sh" ] || die "no site in $REPO"
    [ "$(systemctl is-active "$SERVICE")" = active ] \
        || die "$SERVICE is not running"
    site_answers || die "the site does not answer at $LOCAL_URL/"
    ok "$SERVICE is running and answers at $LOCAL_URL/"
    manage check > /dev/null || die "manage.py check failed"
    manage_debug check > /dev/null \
        || die "manage.py check failed with DEBUG=True"
    ok "manage.py check passes, with and without DEBUG"
    if [ -n "$BACKUP_DIR" ]; then
        command -v mysqldump > /dev/null || die "no mysqldump"
        [ -d "$BACKUP_DIR" ] && [ -w "$BACKUP_DIR" ] \
            || die "cannot write backups to $BACKUP_DIR"
        ok "backups go to $BACKUP_DIR"
    else
        warn "TNNT_BACKUP_DIR is empty: no database backup"
    fi

    if [ "$mode" = on ]; then
        [ -e "$STATE" ] && die "already in test mode ($STATE exists)"
        env_has_debug && die "$ENV_FILE already has test mode's DEBUG line"
        if [ -f "$ENV_FILE" ] && grep -q '^[[:space:]]*DEBUG=' "$ENV_FILE"
        then
            die "$ENV_FILE already sets DEBUG"
        fi
        debug_is_live && die "the running site is already in DEBUG mode"
        ok "the site is in normal mode"
    else
        [ -e "$STATE" ] || die "not in test mode (no $STATE)"
        env_has_debug || die "$ENV_FILE does not have test mode's DEBUG line"
        debug_is_live || warn "the running site is not in DEBUG mode"
        if [ -n "$BOT_SERVICE" ]; then
            systemctl cat "$BOT_SERVICE" > /dev/null 2>&1 \
                || die "no $BOT_SERVICE"
        fi
        ok "the site is in test mode since $(stat -c %y "$STATE" | cut -c1-16)"
    fi

    step "Rehearsing the database work (rolled back)"
    mkdir -p "$STATE_DIR" || die "cannot create $STATE_DIR"
    manage test_mode "$mode" --state "$STATE" --dry-run \
        || die "the rehearsal failed; nothing changed"
}

turn_on() {
    local dry_run=$1
    preflight on
    if [ "$dry_run" = 1 ]; then
        would "back up the database to $BACKUP_DIR"
        would "add DEBUG=True to $ENV_FILE and restart $SERVICE"
        would "turn logins and clan operations on and load the test games"
        would "log in as $TEST_ACCOUNT at $LOCAL_URL/login/"
        printf '\nDry run passed; nothing was changed.\n'
        return
    fi

    if [ -n "$BACKUP_DIR" ]; then
        step "Backing up the database"
        backup_db
    fi

    step "Restarting the site in DEBUG mode"
    env_add_debug || die "cannot write $ENV_FILE; nothing changed"
    if ! restart_site || ! debug_is_live; then
        env_remove_debug
        restart_site
        die "the site did not come back in DEBUG mode; put back to normal"
    fi
    ok "DEBUG is on and the site answers"

    step "Loading the test data"
    if ! manage test_mode on --state "$STATE" --backup "${BACKUP_FILE:-none}"
    then
        env_remove_debug
        restart_site || warn "the site does not answer at $LOCAL_URL/"
        die "loading failed and was rolled back; the site is back in normal mode"
    fi

    step "Checking the site"
    if login_works; then
        ok "logged in as $TEST_ACCOUNT over HTTP"
    else
        warn "logging in as $TEST_ACCOUNT over HTTP failed; check the site, then ./test_mode.sh off"
    fi
    check_public
    printf '\nTest mode is on. Log in as alice, bob, chuck, david, eve, gimli,\n'
    printf 'janet, omghax or sally (password: the same name). Run\n'
    printf './test_mode.sh off before the tournament starts.\n'
}

turn_off() {
    local dry_run=$1
    preflight off
    if [ "$dry_run" = 1 ]; then
        would "back up the database to $BACKUP_DIR"
        would "remove DEBUG=True from $ENV_FILE and stop $SERVICE"
        would "delete the test data and put the switches back, as above"
        would "start $SERVICE in normal mode"
        [ -n "$BOT_SERVICE" ] && would "restart $BOT_SERVICE"
        printf '\nDry run passed; nothing was changed.\n'
        return
    fi

    if [ -n "$BACKUP_DIR" ]; then
        step "Backing up the database"
        backup_db
    fi

    # Stopped, the site can take no test logins while their rows go
    step "Stopping the site"
    env_remove_debug || die "cannot edit $ENV_FILE; nothing changed"
    if ! systemctl stop "$SERVICE"; then
        env_add_debug
        die "cannot stop $SERVICE; still in test mode"
    fi
    ok "$SERVICE stopped, DEBUG removed from $ENV_FILE"

    step "Removing the test data"
    if ! manage test_mode off --state "$STATE"; then
        env_add_debug
        systemctl start "$SERVICE" && wait_for_site \
            || warn "the site does not answer at $LOCAL_URL/"
        die "removing failed and was rolled back; the site is back in test mode"
    fi

    step "Starting the site in normal mode"
    systemctl start "$SERVICE" && wait_for_site \
        || die "the site does not answer at $LOCAL_URL/; check systemctl status $SERVICE"
    debug_is_live && die "the site is still in DEBUG mode; check $ENV_FILE"
    ok "the site answers, without DEBUG"

    if [ -n "$BOT_SERVICE" ]; then
        step "Restarting $BOT_SERVICE"
        if systemctl restart "$BOT_SERVICE"; then
            ok "$BOT_SERVICE restarted"
        else
            warn "could not restart $BOT_SERVICE"
        fi
    fi
    check_public
    printf '\nTest mode is off.\n'
}

check_public() {
    [ -n "$PUBLIC_URL" ] || return 0
    local code
    code=$(http_code "$PUBLIC_URL")
    if [ "$code" = 200 ]; then
        ok "$PUBLIC_URL answers 200"
    else
        warn "$PUBLIC_URL answers ${code:-nothing}"
    fi
}

show_status() {
    local pid
    if env_has_debug; then
        echo "$ENV_FILE: test mode's DEBUG=True is set"
    else
        echo "$ENV_FILE: no test mode DEBUG line"
    fi
    pid=$(systemctl show -p MainPID --value "$SERVICE")
    if [ -n "$pid" ] && [ "$pid" != 0 ] && [ -r "/proc/$pid/environ" ]; then
        if tr '\0' '\n' < "/proc/$pid/environ" | grep -qx 'DEBUG=True'; then
            echo "$SERVICE (pid $pid): running with DEBUG=True"
        else
            echo "$SERVICE (pid $pid): running without DEBUG"
        fi
    else
        echo "$SERVICE: not running"
    fi
    manage test_mode status --state "$STATE"
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
ACTION=$1
DRY_RUN=0
if [ $# = 2 ]; then
    [ "$2" = --dry-run ] || usage
    DRY_RUN=1
fi

exec 9> "$LOCK" || die "cannot open $LOCK"
flock -n 9 || die "another test_mode.sh is running"

case $ACTION in
    on) turn_on "$DRY_RUN" ;;
    off) turn_off "$DRY_RUN" ;;
    status) show_status ;;
    *) usage ;;
esac
