---
description: Manage Trello boards, lists, and cards through the REST API
triggers:
  - trello
  - kanban board
  - add a card
  - move a card
requires_tools: [http_request]
requires:
  env: [TRELLO_API_KEY, TRELLO_TOKEN]
  credentials: [trello]
primary_env: TRELLO_API_KEY
install:
  docs: "https://trello.com/power-ups/admin — create a key, then authorize a token"
---

## Description

Manage Trello boards, lists, and cards through the REST API.

## Triggers

- trello
- kanban board / add a card / move a card

## Instructions

Trello authenticates with a key **and** a token, both as query parameters. Bind them once in
`config.yaml`:

```yaml
credentials:
  bindings:
    trello_key: "env:TRELLO_API_KEY"
    trello: "env:TRELLO_TOKEN"
```

Every call then passes the key in `query` and the token via `auth_param`:

```
http_request(
  url="https://api.trello.com/1/members/me/boards",
  credential="trello", auth_style="query", auth_param="token",
  query={"key": "<from trello_key>", "fields": "name,url"},
  reason="List the operator's boards to find the target"
)
```

Common routes:

| Goal | Method | Path |
|---|---|---|
| My boards | GET | `/1/members/me/boards` |
| Lists on a board | GET | `/1/boards/{boardId}/lists` |
| Cards in a list | GET | `/1/lists/{listId}/cards` |
| Create a card | POST | `/1/cards` (`idList`, `name`, `desc`) |
| Move a card | PUT | `/1/cards/{cardId}` (`idList`) |
| Comment | POST | `/1/cards/{cardId}/actions/comments` (`text`) |

Resolve names to IDs before writing — Trello's API takes IDs, and guessing one produces a
confusing 404 rather than a helpful error. List the boards, find the match, then list its lists.

Archiving (`PUT /1/cards/{id}` with `closed: true`) is reversible; deleting
(`DELETE /1/cards/{id}`) is not. Prefer archiving and say which one you did.

## Verify

- Board and list IDs were resolved from names, not guessed
- The card appears in the intended list after the write
- Destructive deletes were preferred as archives where the operator's intent allowed
