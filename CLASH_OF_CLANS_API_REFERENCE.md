# Clash of Clans API - Complete Reference Documentation

**API Version:** v1  
**Base URL:** `https://api.clashofclans.com/v1`  
**Authentication:** Bearer Token (HTTP Header)  
**Rate Limit:** Developer tier (silver/gold) has throttling limits  

---

## Table of Contents

1. [Authentication & Rate Limiting](#authentication--rate-limiting)
2. [Clans Endpoints](#clans-endpoints)
3. [Players Endpoints](#players-endpoints)
4. [Clan War Leagues](#clan-war-leagues)
5. [Capital Raids](#capital-raids)
6. [Clan Games](#clan-games)
7. [Common Response Objects](#common-response-objects)
8. [Error Codes](#error-codes)

---

## Authentication & Rate Limiting

### Authentication Header
```
Authorization: Bearer <your_api_token>
```

### Rate Limiting
- **Developer (Silver tier):** Basic throttling limits
- **Developer (Gold tier):** Higher throttling limits
- **Response Code 429:** Rate limit exceeded, retry after specified time
- **Rate Limit Headers:**
  - `X-RateLimit-Limit`: Maximum requests allowed in window
  - `X-RateLimit-Remaining`: Requests remaining in current window
  - `Retry-After`: Seconds to wait before retrying (when 429)

### Token IP Whitelist
- Tokens must be IP-restricted for security
- Only requests from whitelisted IPs will be accepted
- Response 403 indicates IP is not whitelisted

---

## Clans Endpoints

### GET /clans/{clanTag}

Retrieve detailed information about a specific clan.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `clanTag` | string | Yes | Clan tag (URL encoded, e.g., `%232PRGP0L22`) |

**Response (200 OK):**
```json
{
  "tag": "#2PRGP0L22",
  "name": "Clan Name",
  "type": "open|inviteOnly|closed",
  "description": "Clan description text",
  "location": {
    "id": 32000060,
    "name": "International",
    "isCountry": false
  },
  "badgeUrls": {
    "small": "https://...",
    "large": "https://...",
    "medium": "https://..."
  },
  "clanLevel": 14,
  "clanPoints": 45230,
  "clanVersusPoints": 32100,
  "requiredTrophies": 2500,
  "warFrequency": "moreThanOncePerWeek|oncePerWeek|lessThanOncePerWeek|never|unknown",
  "warWinStreak": 5,
  "warWins": 325,
  "warTies": 12,
  "warLosses": 18,
  "isWarLogPublic": true,
  "warLeague": {
    "id": 48000000,
    "name": "Champion League I"
  },
  "clanCapital": {
    "capitalHallLevel": 10,
    "districts": [
      {
        "id": 70000001,
        "name": "Barbarian Camp",
        "districtHallLevel": 4,
        "defenseTroopsLost": 0,
        "defenseTroopsKilled": 45,
        "offenseTroopsLost": 120,
        "offenseTroopsKilled": 89
      }
    ]
  },
  "labels": [
    {
      "id": 1,
      "name": "Friendly",
      "iconUrls": {
        "small": "https://...",
        "medium": "https://..."
      }
    }
  ],
  "clanGames": {
    "state": "notStarted|inProgress|ended",
    "startTime": "20240101T000000.000Z",
    "endTime": "20240108T000000.000Z"
  },
  "members": 50,
  "memberList": [
    {
      "tag": "#ABC123DE",
      "name": "Player Name",
      "role": "leader|coLeader|admin|member",
      "expLevel": 300,
      "league": {
        "id": 29000001,
        "name": "Silver I",
        "iconUrls": {
          "small": "https://...",
          "medium": "https://...",
          "large": "https://..."
        }
      },
      "trophies": 5230,
      "versus Trophies": 3200,
      "clanRank": 1,
      "previousClanRank": 1,
      "donations": 450,
      "donationsReceived": 230,
      "campaignProgress": 100,
      "builderBaseLeague": {
        "id": 22000013,
        "name": "Gold League",
        "iconUrls": {
          "small": "https://...",
          "medium": "https://...",
          "large": "https://..."
        }
      },
      "builderBaseTrophies": 4500,
      "versusBattleWins": 150,
      "townHallLevel": 14,
      "townHallWeapon": 5,
      "builderHallLevel": 9
    }
  ]
}
```

**Error Codes:**
- `400`: Invalid clan tag format
- `401`: Unauthorized (invalid token)
- `403`: Forbidden (IP not whitelisted)
- `404`: Clan not found
- `429`: Rate limit exceeded

---

### GET /clans/{clanTag}/members

Get list of clan members with pagination.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `clanTag` | string | Yes | - | Clan tag (URL encoded) |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "tag": "#ABC123DE",
      "name": "Player Name",
      "role": "leader|coLeader|admin|member",
      "expLevel": 300,
      "league": {
        "id": 29000001,
        "name": "Silver I"
      },
      "trophies": 5230,
      "versusTrophies": 3200,
      "clanRank": 1,
      "donations": 450,
      "donationsReceived": 230,
      "townHallLevel": 14
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /clans/{clanTag}/warlog

Retrieve clan war log history.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `clanTag` | string | Yes | - | Clan tag (URL encoded) |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "type": "clanWar|clanWarLeague",
      "clanTag": "#2PRGP0L22",
      "clanLevel": 14,
      "attacksUsed": 45,
      "stars": 125,
      "destructionPercentage": 87.5,
      "expEarned": 4500,
      "newExpEarned": 450,
      "clan": {
        "tag": "#2PRGP0L22",
        "name": "Clan Name",
        "badgeUrls": {
          "small": "https://..."
        }
      },
      "opponent": {
        "tag": "#OPPONENT1",
        "name": "Opponent Clan",
        "badgeUrls": {
          "small": "https://..."
        }
      },
      "endTime": "20240101T120000.000Z"
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /clans/{clanTag}/currentwar

Retrieve current clan war information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `clanTag` | string | Yes | Clan tag (URL encoded) |

**Response (200 OK):**
```json
{
  "state": "notInWar|preparation|inWar|warEnded",
  "warStartTime": "20240101T160000.000Z",
  "warEndTime": "20240103T160000.000Z",
  "teamSize": 50,
  "attacksPlanned": 0,
  "preparationStartTime": "20240101T140000.000Z",
  "clan": {
    "tag": "#2PRGP0L22",
    "name": "Clan Name",
    "badgeUrls": {
      "small": "https://..."
    },
    "clanLevel": 14,
    "attacks": 45,
    "stars": 125,
    "destructionPercentage": 87.5,
    "members": [
      {
        "tag": "#ABC123DE",
        "name": "Player Name",
        "townHallLevel": 14,
        "mapPosition": 1,
        "attacks": [
          {
            "attacker": "#ABC123DE",
            "defender": "#DEFENDER1",
            "stars": 3,
            "destructionPercentage": 100,
            "order": 1,
            "duration": 180
          }
        ],
        "bestOpponentAttack": {
          "attacker": "#DEFENDER1",
          "defender": "#ABC123DE",
          "stars": 2,
          "destructionPercentage": 75,
          "order": 2,
          "duration": 150
        }
      }
    ]
  },
  "opponent": {
    "tag": "#OPPONENT1",
    "name": "Opponent Clan",
    "badgeUrls": {
      "small": "https://..."
    },
    "clanLevel": 13,
    "attacks": 40,
    "stars": 100,
    "destructionPercentage": 75.2,
    "members": []
  }
}
```

**War States:**
- `notInWar`: No active war
- `preparation`: Preparation day before war
- `inWar`: War is currently active
- `warEnded`: War has ended

---

### GET /clans/{clanTag}/capitalraidseasons

Get clan capital raid seasons information.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `clanTag` | string | Yes | - | Clan tag (URL encoded) |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "state": "ongoing|ended",
      "startTime": "20240101T000000.000Z",
      "endTime": "20240108T000000.000Z",
      "capitalTotalLoot": 500000,
      "raiderTotalLoot": 300000,
      "defenderTotalLoot": 200000,
      "raidAttacks": 45,
      "totalAttacks": 50,
      "defensesDestroyed": 120,
      "totalDestructions": 150,
      "attackLog": [
        {
          "attacker": {
            "tag": "#ABC123DE",
            "name": "Attacker Name"
          },
          "defender": {
            "tag": "#DEFENDER1",
            "name": "Defender Name"
          },
          "stars": 3,
          "destructionPercentage": 100,
          "order": 1,
          "duration": 180,
          "loot": 10000
        }
      ],
      "defenseLog": [
        {
          "attacker": {
            "tag": "#DEFENDER1",
            "name": "Defending Player"
          },
          "defender": {
            "tag": "#ABC123DE",
            "name": "Attacker Player"
          },
          "stars": 2,
          "destructionPercentage": 75,
          "order": 1,
          "duration": 150,
          "loot": 5000
        }
      ],
      "clan": {
        "tag": "#2PRGP0L22",
        "name": "Clan Name",
        "level": 10,
        "badgeUrls": {
          "small": "https://..."
        }
      },
      "districts": [
        {
          "id": 70000001,
          "name": "Barbarian Camp",
          "districtHallLevel": 4,
          "destructionPercent": 50,
          "stars": 2,
          "attackCount": 3,
          "totalLooted": 15000
        }
      ]
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

## Players Endpoints

### GET /players/{playerTag}

Retrieve detailed information about a specific player.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `playerTag` | string | Yes | Player tag (URL encoded, e.g., `%232PRGP0L22`) |

**Response (200 OK):**
```json
{
  "tag": "#ABC123DE",
  "name": "Player Name",
  "townHallLevel": 14,
  "townHallWeapon": 5,
  "expLevel": 300,
  "trophies": 5230,
  "bestTrophies": 6500,
  "warStars": 450,
  "attackWins": 350,
  "defenseWins": 200,
  "builderHallLevel": 9,
  "builderBaseTrophies": 4500,
  "bestBuilderBaseTrophies": 5000,
  "role": "member|admin|coLeader|leader",
  "warPreference": "out|in",
  "donations": 450,
  "donationsReceived": 230,
  "clanCapitalContribution": 12000,
  "clan": {
    "tag": "#2PRGP0L22",
    "name": "Clan Name",
    "badgeUrls": {
      "small": "https://..."
    }
  },
  "league": {
    "id": 29000001,
    "name": "Silver I",
    "iconUrls": {
      "small": "https://...",
      "medium": "https://...",
      "large": "https://..."
    }
  },
  "builderBaseLeague": {
    "id": 22000013,
    "name": "Gold League",
    "iconUrls": {
      "small": "https://...",
      "medium": "https://...",
      "large": "https://..."
    }
  },
  "versusBattleWins": 150,
  "troops": [
    {
      "name": "Barbarian",
      "level": 14,
      "maxLevel": 14,
      "village": "home|builderBase"
    }
  ],
  "heroes": [
    {
      "name": "Barbarian King",
      "level": 80,
      "maxLevel": 80,
      "village": "home|builderBase"
    }
  ],
  "spells": [
    {
      "name": "Lightning Spell",
      "level": 11,
      "maxLevel": 12,
      "village": "home"
    }
  ],
  "labels": [
    {
      "id": 1,
      "name": "Friendly",
      "iconUrls": {
        "small": "https://...",
        "medium": "https://..."
      }
    }
  ],
  "achievements": [
    {
      "name": "Bigger Coffers",
      "stars": 3,
      "value": 999999,
      "target": 1000000,
      "info": "Accumulated 1,000,000 Gold!",
      "completionInfo": "3 stars"
    }
  ],
  "playerHouse": {
    "elements": [
      {
        "id": 1,
        "element": "background"
      }
    ]
  }
}
```

---

## Clan War Leagues

### GET /clans/{clanTag}/warleagues

Get clan war league standings.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `clanTag` | string | Yes | Clan tag (URL encoded) |

**Response (200 OK):**
```json
{
  "tag": "#2PRGP0L22",
  "name": "Clan Name",
  "state": "groupsOpen|preparation|inWar|ended|notInWar",
  "season": "20240101",
  "clans": [
    {
      "tag": "#2PRGP0L22",
      "clanLevel": 14,
      "badgeUrls": {
        "small": "https://..."
      },
      "name": "Clan Name",
      "members": 50,
      "stars": 125,
      "destructionPercentage": 87.5,
      "attacks": 45
    }
  ]
}
```

---

### GET /warleagues/{leagueId}

Get specific war league information.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `leagueId` | integer | Yes | War league ID |

**Response (200 OK):**
```json
{
  "id": 48000000,
  "name": "Champion League I",
  "iconUrls": {
    "small": "https://...",
    "medium": "https://..."
  }
}
```

---

### GET /warleagues

Get list of all war leagues.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": 48000020,
      "name": "Unranked",
      "iconUrls": {
        "small": "https://..."
      }
    },
    {
      "id": 48000001,
      "name": "Bronze League III",
      "iconUrls": {
        "small": "https://..."
      }
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

## Capital Raids

### GET /clans/{clanTag}/capitalraidseasons (Already documented above)

Capital raid seasons include:
- **Raid State:** ongoing | ended
- **Raid Attacks:** Attackers log details
- **Defense Log:** Defenders log details
- **District Info:** Individual capital district stats
- **Loot Tracking:** Gold and resources looted

**Capital District Details:**
```json
{
  "id": 70000001,
  "name": "Barbarian Camp",
  "districtHallLevel": 4,
  "destructionPercent": 50,
  "stars": 2,
  "attackCount": 3,
  "totalLooted": 15000
}
```

---

## Clan Games

### Clan Games Data (via GET /clans/{clanTag})

Clan games information is available as part of the clan response:

```json
{
  "clanGames": {
    "state": "notStarted|inProgress|ended",
    "startTime": "20240101T000000.000Z",
    "endTime": "20240108T000000.000Z"
  }
}
```

---

## Common Response Objects

### Player Object (Compact)
```json
{
  "tag": "#ABC123DE",
  "name": "Player Name",
  "expLevel": 300,
  "trophies": 5230,
  "versusTrophies": 3200,
  "townHallLevel": 14,
  "builderHallLevel": 9
}
```

### Clan Object (Compact)
```json
{
  "tag": "#2PRGP0L22",
  "name": "Clan Name",
  "badgeUrls": {
    "small": "https://...",
    "large": "https://...",
    "medium": "https://..."
  },
  "clanLevel": 14
}
```

### League Object
```json
{
  "id": 29000001,
  "name": "Silver I",
  "iconUrls": {
    "small": "https://...",
    "medium": "https://...",
    "large": "https://..."
  }
}
```

### Troop/Hero/Spell Object
```json
{
  "name": "Barbarian",
  "level": 14,
  "maxLevel": 14,
  "village": "home|builderBase"
}
```

### Badge URLs
```json
{
  "small": "https://api-assets.clashofclans.com/badges/..._95.png",
  "large": "https://api-assets.clashofclans.com/badges/..._340.png",
  "medium": "https://api-assets.clashofclans.com/badges/..._200.png"
}
```

### Pagination Object
```json
{
  "paging": {
    "cursors": {
      "before": "cursor_value",
      "after": "cursor_value"
    }
  }
}
```

---

## Error Codes

| Code | Name | Description | Recovery |
|------|------|-------------|----------|
| `400` | Bad Request | Invalid request parameters (invalid tag format, invalid limit, etc.) | Check parameter format and values |
| `401` | Unauthorized | Invalid API token or token not provided | Verify API token is correct |
| `403` | Forbidden | IP not whitelisted for the token, or token permissions insufficient | Add request IP to token whitelist |
| `404` | Not Found | Requested clan/player not found | Verify tag is correct and publicly available |
| `429` | Too Many Requests | Rate limit exceeded | Wait before retrying, check `Retry-After` header |
| `500` | Internal Server Error | Server-side error | Retry request after delay |
| `502` | Bad Gateway | API gateway error | Retry request |
| `503` | Service Unavailable | API service unavailable | Retry request |
| `504` | Gateway Timeout | Request timed out | Retry request with longer timeout |

---

## Search Endpoints

### GET /clans

Search for clans by various criteria.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | No | - | Clan name (can be partial) |
| `warFrequency` | string | No | - | never\|lessThanOncePerWeek\|oncePerWeek\|moreThanOncePerWeek |
| `locationId` | integer | No | - | Location ID (see locations endpoint) |
| `minMembers` | integer | No | - | Minimum members (1-50) |
| `maxMembers` | integer | No | - | Maximum members (1-50) |
| `minClanLevel` | integer | No | - | Minimum clan level (1-25) |
| `maxClanLevel` | integer | No | - | Maximum clan level (1-25) |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |
| `labelIds` | string | No | - | Comma-separated label IDs |

**Response (200 OK):**
```json
{
  "items": [
    {
      "tag": "#2PRGP0L22",
      "name": "Clan Name",
      "type": "open|inviteOnly|closed",
      "location": {
        "id": 32000060,
        "name": "International"
      },
      "badgeUrls": {
        "small": "https://..."
      },
      "clanLevel": 14,
      "clanPoints": 45230,
      "members": 50,
      "requiredTrophies": 2500,
      "warFrequency": "moreThanOncePerWeek",
      "warWins": 325,
      "warTies": 12,
      "warLosses": 18
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /players

Search for players by various criteria.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `name` | string | No | - | Player name (can be partial) |
| `minTrophies` | integer | No | - | Minimum trophies |
| `maxTrophies` | integer | No | - | Maximum trophies |
| `minBuilderBaseTrophies` | integer | No | - | Minimum builder base trophies |
| `maxBuilderBaseTrophies` | integer | No | - | Maximum builder base trophies |
| `minClanLevel` | integer | No | - | Minimum clan level for members |
| `maxClanLevel` | integer | No | - | Maximum clan level for members |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |
| `labelIds` | string | No | - | Comma-separated label IDs |

**Response (200 OK):**
```json
{
  "items": [
    {
      "tag": "#ABC123DE",
      "name": "Player Name",
      "townHallLevel": 14,
      "expLevel": 300,
      "trophies": 5230,
      "bestTrophies": 6500,
      "warStars": 450,
      "attackWins": 350,
      "defenseWins": 200,
      "builderHallLevel": 9,
      "builderBaseTrophies": 4500,
      "clan": {
        "tag": "#2PRGP0L22",
        "name": "Clan Name"
      },
      "league": {
        "id": 29000001,
        "name": "Silver I"
      }
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

## Reference Data Endpoints

### GET /locations

Get list of all locations.

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": 32000000,
      "name": "Afghanistan",
      "isCountry": true
    },
    {
      "id": 32000060,
      "name": "International",
      "isCountry": false
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /locations/{locationId}

Get specific location details.

**Response (200 OK):**
```json
{
  "id": 32000060,
  "name": "International",
  "isCountry": false
}
```

---

### GET /locations/{locationId}/rankings/players

Get top players in a location.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `locationId` | integer | Yes | - | Location ID |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "rank": 1,
      "tag": "#ABC123DE",
      "name": "Top Player",
      "expLevel": 300,
      "trophies": 7500,
      "townHallLevel": 14,
      "clan": {
        "tag": "#2PRGP0L22",
        "name": "Clan Name"
      },
      "league": {
        "id": 29000001,
        "name": "Diamond I"
      }
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /locations/{locationId}/rankings/clans

Get top clans in a location.

**Parameters:**
| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `locationId` | integer | Yes | - | Location ID |
| `limit` | integer | No | 50 | Items per page (1-50) |
| `after` | string | No | - | Pagination cursor |
| `before` | string | No | - | Pagination cursor |

**Response (200 OK):**
```json
{
  "items": [
    {
      "rank": 1,
      "tag": "#2PRGP0L22",
      "name": "Top Clan",
      "clanLevel": 14,
      "clanPoints": 50000,
      "members": 50,
      "badgeUrls": {
        "small": "https://..."
      },
      "location": {
        "id": 32000060,
        "name": "International"
      }
    }
  ],
  "paging": {
    "cursors": {
      "before": "...",
      "after": "..."
    }
  }
}
```

---

### GET /labels/clans

Get all clan labels.

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": 1,
      "name": "Friendly",
      "iconUrls": {
        "small": "https://...",
        "medium": "https://..."
      }
    }
  ]
}
```

---

### GET /labels/players

Get all player labels.

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": 1,
      "name": "Friendly",
      "iconUrls": {
        "small": "https://...",
        "medium": "https://..."
      }
    }
  ]
}
```

---

## Data Types & Enumerations

### War Frequency
- `never`
- `lessThanOncePerWeek`
- `oncePerWeek`
- `moreThanOncePerWeek`
- `unknown`

### Clan Type
- `open`
- `inviteOnly`
- `closed`

### Player Role
- `leader`
- `coLeader`
- `admin`
- `member`

### Village Type
- `home`
- `builderBase`

### War State
- `notInWar`
- `preparation`
- `inWar`
- `warEnded`

### War League State
- `groupsOpen`
- `preparation`
- `inWar`
- `ended`
- `notInWar`

### Raid State
- `ongoing`
- `ended`

### Clan Games State
- `notStarted`
- `inProgress`
- `ended`

### War Preference
- `in`
- `out`

---

## Best Practices

1. **Caching:** Cache responses appropriately (5-10 minutes for clan/player data)
2. **Rate Limiting:** Implement exponential backoff for 429 responses
3. **Tag Encoding:** Always URL-encode clan/player tags (# becomes %23)
4. **Pagination:** Use cursors for large result sets
5. **Error Handling:** Check HTTP status codes and implement retry logic
6. **IP Whitelisting:** Keep API token IP whitelisting configured
7. **Token Security:** Never expose tokens in client-side code
8. **Timeout:** Set reasonable request timeouts (30+ seconds recommended)

---

## Example Requests

### Get Clan Information
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.clashofclans.com/v1/clans/%232PRGP0L22"
```

### Get Player Information
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.clashofclans.com/v1/players/%23ABC123DE"
```

### Get Current War
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.clashofclans.com/v1/clans/%232PRGP0L22/currentwar"
```

### Search Clans
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.clashofclans.com/v1/clans?name=dragon&minClanLevel=10&maxMembers=50"
```

---

## Version History

**API v1** (Current)
- All endpoints documented above
- Support for Clan Capital
- Support for Clan Games
- Support for War Leagues
- Support for Capital Raids
- Pagination support via cursors
- Label support for clans and players

---

**Last Updated:** January 28, 2026  
**Official Documentation:** https://developer.clashofclans.com/api-docs
