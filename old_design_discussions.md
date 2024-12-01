# Old TNNT scoreboard design discussions

This document exists to preserve design discussions about features for the TNNT
scoreboard which haven't actually been discussed in a while. The idea is that if
a suggestion comes back up for discussion, this will be a reference point for
its history, while clearing the clutter out of the forum used for active TNNT
design discussions.

The intended style is to summarize the relevant points rather than copying the
raw back-and-forth.

This doesn't cover design discussions about the TNNT game binary, only the
scoreboard (other than if a proposed scoreboard feature is infeasible because it
would be technically challenging on the game side).

While this file covers a lot of reasons why various features were rejected,
don't assume that every idea in here has been considered and rejected. Sometimes
an idea just never got enough interest from anyone to get implemented.

The discussions in this file date from prior to the 2024 tournament, and do not
cover anything during or after that tournament.

## Leaderboards

There are several reasons why a proposed leaderboard is unlikely to be
implemented. Sometimes the leaderboard just isn't compelling enough to dedicate
space in the list of leaderboards to (we don't want to have 100 leaderboards, 90
of which are uninteresting to the average player). Other times there's a more
concrete objection.

Goodhart's Law is a useful thing to keep in mind when designing leaderboards:
"When a measure becomes a target, it ceases to be a good measure."

### OK (but unlikely) leaderboards

Some of these were proposed as trophies back in the unified-scoring era of TNNT,
and would now exist as leaderboards instead.

- Highest ascension ratio. It would need to avoid the problem of someone
  creating accounts until they get a win on the first game of one and then stop
  using that account. This could be accomplished by:
    1. setting a minimum number of ascensions
    2. using the number of ascensions as a tiebreaker and showing it on
       the leaderboard for extra context
    3. using DCSS tournament rules and computing win rate under the
       assumption that the next game will be a loss
  This leaderboard would also have to be player-only in tune with the principle
  that a clan shouldn't be disincentivized from including a poor player.
- Most kills of deathmatch opponents.
- Latest start time of an ascension. This would largely be a realtime
  speedrunning one like First Ascension is, but would add excitement to the
  final day of the tournament.
- Most loot hauled to the high altar in an ascension. This might end up looking
  a lot like the Highest Scoring Game leaderboard, but then again it might not,
  if Highest Scoring Game is dominated by extinctionist types of games.
- Most games with all 12 vanilla conducts broken, similar to Junethack awards
  for this. It wouldn't include TNNT tracked conducts because some of them
  require the game to be all but won to break (kill a Rider) and even if the
  "never kill" ones were left off, you'd have to do a whole bunch of other stuff
  like finding an artifact, finding an amulet of life saving and wasting it,
  remembering to write Elbereth, and randomly finding bones.
- Most unique unique deaths - deaths that your player (or clan) has which no
  other player (or clan) does. Interesting in that these can be "taken away" by
  someone else getting the same death. Currently, you can see this in
  non-leaderboard form on the unique deaths summary page by looking for unique
  deaths which have a count of 1 for either players or clans.

### Very unlikely leaderboards

- Most bag of holding explosions. The spirit of the idea is "who accidentally
  blew up their BoH the most times", but it's likely to be quickly distorted by
  "who polypiled for BoHs and blew them up the most".
- Most scummed games. Scumming is tolerated, but not intended to be a goal to
  strive for.
- Most deaths by (petrification, drawbridge, lava, illness, ...). Since "die in
  a specific way" is not even treated as a valid achievement, there probably
  shouldn't be multiple leaderboards for them.
- Most times an ascension was completed with a helm of opposite alignment.
- Lowest AC at time of death. Likely to turn into "lowest AC, then die in any
  number of ways". There's already an achievement for ultra-low AC.
- Most deaths to a difficulty 0 or 1 monster.
- Most trickeries. No one has died to a trickery in at least the first six years
  of TNNT.
- Highest level-to-turns ratio, as measured by the first turn you arrived at a
  "new deepest" level. There are obvious problems with this such as levelport
  and digging holes, and it would be weird if using either excluded the game
  from consideration.
- Most astral splats. These would be a rarer subset of post-amulet splats and
  the distinction probably isn't worth making.

## Trophies

Trophies proposed at some point:
- Streaking Streaker: have a streak of 2 or more nudist ascensions.
- Bug Bounty: be the first reporter of a vanilla (or TNNT?) bug that the devteam
  (or TNNT devs?) verifies. It would have to be manually awarded by a tournament
  admin.
- Trophy for a player dying to your deathmatch character. However, this might be
  weird since you don't have much control over the deathmatch character other
  than to a limited extent over their inventory and the timing of their
  ascension.

## Unique deaths

- Add multi_reasons as distinct unique deaths, since multi_reasons just like
  unique deaths range from common to esoteric and difficult. Under this system,
  the "while=" field in the xlogfile would normalize into a "died, while XYZ"
  unique death and it would be possible to get two unique deaths from the same
  game (i.e. "killed by a jackal, while frozen by a potion" becomes "killed by a
  jackal" and "frozen by a potion". This would be tricky to implement, which is
  perhaps why it hasn't gotten a serious look.
- Page for comparing unique deaths: input 2 players, or clans, and it will do a
  side by side comparison of their unique death lists, highlighting ones that
  one player has but the other doesn't.

## Miscellaneous suggestions

- Make the Fastest Realtime leaderboard respect in-game time only (the xlogfile
  "realtime" field), not wallclock time (the delta between end and start time),
  thereby allowing real-time speedrunners the ability to take a break.
- The Earliest Ascension leaderboard has a timezone bias, which favors players
  in the Americas in particular, and to a lesser extent east Asia and Australia:
  since TNNT starts at midnight UTC, it's late at night for Europe, Africa, and
  western Asia. Make it timezone-agnostic by basing it on the shortest delta
  between the start time of a player's first game (which doesn't have to end in
  an ascension), and the end time of that player's earliest ascension. Name the
  leaderboard "Fastest Time to First Ascension".
  - The main problem with this proposal is that it can be gamed - a player can
    use a sockpuppet account to get a fresh crack at a "first game start", and
    if this is done before the clan freeze deadline, they can insert an account
    that successfully gets a short time-to-first-ascension into their clan
    instead of their normal one. A cutoff threshold (i.e. accounts whose first
    game started after a certain time, say 1 or 2 days into the tournament)
    might work here, but since there are more than a handful of players capable
    of ascending in a few hours, it might not either.
