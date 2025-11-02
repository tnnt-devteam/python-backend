# TNNT REST API Documentation

## Overview

The November NetHack Tournament (TNNT) provides a public REST API for
accessing tournament data. This API enables developers to build IRC bots,
statistics tools, and other integrations with real-time tournament
information.

**Base URL**: `https://tnnt.org/api/`

## Key Features

- **Read-only access** - All endpoints are GET requests
- **JSON responses** - All data returned in JSON format
- **No authentication required** - Public data only
- **Rate limited** - 100 requests per minute per IP address
- **Paginated results** - Default 100 items per page where applicable
- **CORS enabled** - Accessible from web browsers

## Endpoints

### Players

#### List All Players
```
GET /api/players/
```
Returns a paginated list of all players with at least one game.

**Response fields:**
- `name` - Player username
- `clan` - Clan name (null if not in a clan)
- `wins` - Number of ascensions
- `total_games` - Total games played
- `ratio` - Win percentage

**Example:**
```bash
curl https://tnnt.org/api/players/
```

#### Get Player Details
```
GET /api/players/{name}/
```
Returns detailed information about a specific player including trophies.

**Response fields:**
- All fields from player list plus:
- `games_scummed` - Number of start-scummed games
- `unique_deaths` - Count of unique death types
- `unique_achievements` - Count of unique achievements earned
- `longest_streak` - Longest winning streak
- `zscore` - Statistical Z-score
- `trophies` - Array of earned trophies with name and description

**Example:**
```bash
curl https://tnnt.org/api/players/copperwater/
```

#### Get Player's Recent Games
```
GET /api/players/{name}/recent_games/
```
Returns the player's 10 most recent games with achievements.

**Response fields per game:**
- `player` - Player name
- `role` - Character role (3-letter code)
- `race` - Character race (3-letter code)
- `gender` - Character gender (Mal/Fem)
- `align` - Character alignment (Law/Neu/Cha)
- `points` - Final score
- `turns` - Number of turns played
- `death` - Death message or "ascended"
- `endtime` - Game end timestamp (ISO 8601)
- `won` - Boolean, true if ascended
- `achievements` - Array of achievements earned in this game

**Example:**
```bash
curl https://tnnt.org/api/players/spazm/recent_games/
```

#### Get Player's Achievements
```
GET /api/players/{name}/achievements/
```
Returns all unique achievements earned by the player.

**Response fields per achievement:**
- `name` - Achievement name
- `description` - Achievement description
- `ingameid` - Internal achievement ID

**Example:**
```bash
curl https://tnnt.org/api/players/hothraxxa/achievements/
```

#### Get Player's Unique Deaths
```
GET /api/players/{name}/unique_deaths/
```
Returns count and list of unique death types for the player.

**Response fields:**
- `count` - Total number of unique deaths
- `deaths` - Array of normalized death strings

**Example:**
```bash
curl https://tnnt.org/api/players/k2/unique_deaths/
```

#### Get Player's Winning Streaks
```
GET /api/players/{name}/streaks/
```
Returns information about the player's winning streaks.

**Response fields per streak:**
- `length` - Number of consecutive wins
- `games` - Array of game IDs in the streak
- `active` - Boolean, true if streak is still active

**Example:**
```bash
curl https://tnnt.org/api/players/Prowler/streaks/
```

### Clans

#### List All Clans
```
GET /api/clans/
```
Returns a list of all clans with their members.

**Response fields:**
- `name` - Clan name
- `wins` - Total clan ascensions
- `total_games` - Total games played by clan
- `ratio` - Win percentage
- `members` - Array of clan members (condensed player info)
- `trophies` - Array of clan trophies

**Example:**
```bash
curl https://tnnt.org/api/clans/
```

#### Get Clan Details
```
GET /api/clans/{name}/
```
Returns detailed information about a specific clan.

**Response:** Same as clan list but for single clan.

**Example:**
```bash
curl https://tnnt.org/api/clans/teamsplat/
```

### Tournament Data

#### Get Leaderboards
```
GET /api/leaderboards/
```
Returns top 10 rankings for various categories.

**Response structure:**
```json
{
  "players": {
    "most_wins": [...],
    "most_games": [...],
    "highest_score": [...]
  },
  "clans": {
    "most_wins": [...],
    "most_games": [...]
  }
}
```

**Example:**
```bash
curl https://tnnt.org/api/leaderboards/
```

#### Get Tournament Scoreboard
```
GET /api/scoreboard/
```
Returns overall tournament standings.

**Response fields:**
- `tournament` - Tournament name/year
- `players` - Top 50 players by wins
- `clans` - Top 20 clans by wins
- `last_updated` - Timestamp of most recent game

**Example:**
```bash
curl https://tnnt.org/api/scoreboard/
```

#### Get Recent Events
```
GET /api/recent-events/
```
Returns achievements and trophies from the last hour.

**Response fields:**
- `achievements` - Array of recent achievements with:
  - `player` - Player who earned it
  - `achievement` - Achievement name
  - `timestamp` - When it was earned
- `trophies` - Array of recent trophy awards (currently empty, future feature)

**Example:**
```bash
curl https://tnnt.org/api/recent-events/
```

## Pagination

List endpoints support pagination using query parameters:

- `limit` - Number of results per page (default: 100)
- `offset` - Number of results to skip

**Example:**
```bash
# Get players 11-20
curl "https://tnnt.org/api/players/?limit=10&offset=10"
```

## Rate Limiting

The API enforces a rate limit of 100 requests per minute per IP address.
If you exceed this limit, you'll receive a 429 (Too Many Requests) response.

For high-volume applications, consider:
- Caching responses locally
- Batching requests where possible
- Implementing exponential backoff on rate limit errors

## Data Freshness

- Game data is polled from game servers every 5 minutes
- Statistics are aggregated immediately after polling completes
- Expect up to 5 minute delay between game completion and API availability

## Example Integrations

### IRC Bot (Python)
```python
import requests
import time

BASE_URL = "https://tnnt.org/api"

def check_recent_achievements():
    """Check for new achievements in the last hour"""
    response = requests.get(f"{BASE_URL}/recent-events/")
    if response.status_code == 200:
        data = response.json()
        for achievement in data['achievements']:
            print(f"{achievement['player']} earned {achievement['achievement']}")
    time.sleep(60)  # Check every minute

def lookup_player(name):
    """Get player information"""
    response = requests.get(f"{BASE_URL}/players/{name}/")
    if response.status_code == 200:
        player = response.json()
        return f"{player['name']}: {player['wins']} wins, {player['total_games']} games"
    elif response.status_code == 404:
        return f"Player {name} not found"
    return "Error fetching player data"
```

### Web Dashboard (JavaScript)
```javascript
async function getLeaderboards() {
    const response = await fetch('https://tnnt.org/api/leaderboards/');
    const data = await response.json();

    // Display most wins leaderboard
    const winsList = document.getElementById('wins-leaderboard');
    data.players.most_wins.forEach(player => {
        const li = document.createElement('li');
        li.textContent = `${player.name}: ${player.wins} wins`;
        winsList.appendChild(li);
    });
}

async function getPlayerDetails(playerName) {
    const response = await fetch(`https://tnnt.org/api/players/${playerName}/`);
    if (response.ok) {
        const player = await response.json();
        console.log(`${player.name} has ${player.trophies.length} trophies`);
    }
}
```

### Command Line Tool (Bash)
```bash
#!/bin/bash

# Get current tournament standings
curl -s https://tnnt.org/api/scoreboard/ | jq '.players[:5]'

# Check a player's recent games
PLAYER="copperwater"
curl -s "https://tnnt.org/api/players/${PLAYER}/recent_games/" | \
  jq '.[] | "\(.endtime): \(.role)\(.race) - \(.death)"'

# Monitor for new achievements
while true; do
    curl -s https://tnnt.org/api/recent-events/ | \
      jq '.achievements[] | "\(.timestamp): \(.player) - \(.achievement)"'
    sleep 600  # Check every 10 minutes
done
```

## Data Types

### Achievement Object
```json
{
  "name": "Ringing in My Ears",
  "description": "Get the Bell of Opening",
  "ingameid": "V01"
}
```

### Trophy Object
```json
{
  "name": "Birdie",
  "description": "Finish a game in under 2000 turns"
}
```

### Game Object
```json
{
  "player": "spazm",
  "role": "Bar",
  "race": "Hum",
  "gender": "Mal",
  "align": "Cha",
  "points": 1604682,
  "turns": 57827,
  "death": "ascended",
  "endtime": "2024-11-30T21:47:15Z",
  "won": true,
  "achievements": [...]
}
```

## Error Handling

The API uses standard HTTP status codes:

- `200 OK` - Request successful
- `404 Not Found` - Player/clan not found
- `429 Too Many Requests` - Rate limit exceeded
- `500 Internal Server Error` - Server error

Error responses include a JSON body with error details:
```json
{
  "detail": "Not found."
}
```

## CORS Configuration

The API allows cross-origin requests from:
- `https://tnnt.org`
- `https://www.tnnt.org`
- `http://localhost` (for development)

If you need access from a different origin, please contact the tournament
administrators.

## Support

For API issues or feature requests, please:
- Report issues at: https://github.com/tnnt-devteam/python-backend/issues
- Contact tournament administrators on IRC: #tnnt on irc.libera.chat

## Terms of Use

- This API is provided free for community use
- Please respect rate limits
- Do not use for commercial purposes without permission
- Credit TNNT when displaying tournament data

## Version History

- **v1.0** (2025-09-01) - Initial public API release
  - Core endpoints for players, clans, and tournament data
  - Rate limiting and CORS support
  - Pagination for list endpoints
