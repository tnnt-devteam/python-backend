#!/bin/bash
# Given a path to the root of the TNNT game source, output YAML to stdout
# containing all of the TNNT achievement names, descriptions, and xlogfile
# fields/bits in a scoreboard-ready format (one that can be passed to manage.py
# loaddata).

if [ -z "$1" ]; then
  echo "Usage: script /path/to/tnnt [ > achievements.yaml ]" >&2
  exit 1
fi

if [ ! -d "$1" ]; then
  echo That path does not exist.
  exit 1
fi

if [ ! -f "$1/util/tnnt_ach_to_yaml.c" ]; then
  echo Requires util/tnnt_ach_to_yaml.c in TNNT repo to function. >&2
  exit 1
fi

# tnnt_achivements.yaml is build dynamically by a utility script, based on the
# contents of tnnt_achivements.h.
if cd "$1/util" && make --silent tnnt_achievements.yaml; then
  cat tnnt_achievements.yaml
else
  echo Error building tnnt_achievements.yaml. >&2
  exit 1
fi
