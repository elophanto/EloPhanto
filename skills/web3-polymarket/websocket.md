# WebSocket

Three channels for real-time data. Market and sports channels are public; user channel requires API credentials.

## Channels

| Channel | Endpoint | Auth |
|---------|----------|------|
| Market | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | No |
| User | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | Yes |
| Sports | `wss://sports-api.polymarket.com/ws` | No |

## Market Channel

Public. Subscribes by **asset IDs** (token IDs).

### Subscribe

```json
{
  "assets_ids": ["TOKEN_ID_1", "TOKEN_ID_2"],
  "type": "market",
  "custom_feature_enabled": true
}
```

Set `custom_feature_enabled: true` to enable `best_bid_ask`, `new_market`, and `market_resolved` events.

### Event Types

| Event | Trigger | Key Fields |
|-------|---------|------------|
| `book` | On subscribe + when trade affects book | `bids[]`, `asks[]`, `hash`, `timestamp` |
| `price_change` | Order placed or cancelled | `price_changes[]` with `price`, `size`, `side`, `best_bid`, `best_ask` |
| `last_trade_price` | Trade executed | `price`, `side`, `size`, `fee_rate_bps` |
| `tick_size_change` | Price hits >0.96 or <0.04 | `old_tick_size`, `new_tick_size` |
| `best_bid_ask` | Top-of-book changes | `best_bid`, `best_ask`, `spread` |
| `new_market` | Market created | `question`, `assets_ids`, `outcomes` |
| `market_resolved` | Market resolved | `winning_asset_id`, `winning_outcome` |

Events requiring `custom_feature_enabled: true`: `best_bid_ask`, `new_market`, `market_resolved`.

**`tick_size_change` is critical for bots** — if tick size changes and you use the old one, orders are rejected.

A `price_change` with `size: "0"` means the price level was removed from the book.

### Example Messages

```json
// book
{
  "event_type": "book",
  "asset_id": "TOKEN_ID",
  "market": "0xCONDITION_ID",
  "bids": [{"price": ".48", "size": "30"}],
  "asks": [{"price": ".52", "size": "25"}],
  "timestamp": "123456789000",
  "hash": "0x..."
}
```

```json
// price_change
{
  "event_type": "price_change",
  "market": "0xCONDITION_ID",
  "price_changes": [{
    "asset_id": "TOKEN_ID",
    "price": "0.5",
    "size": "200",
    "side": "BUY",
    "hash": "...",
    "best_bid": "0.5",
    "best_ask": "1"
  }],
  "timestamp": "..."
}
```

## User Channel

Authenticated. Subscribes by **condition IDs** (market IDs), not asset IDs. The `markets` field is optional — omit it to receive events for all markets.

### Subscribe

```json
{
  "auth": {
    "apiKey": "your-api-key",
    "secret": "your-api-secret",
    "passphrase": "your-passphrase"
  },
  "markets": ["0xCONDITION_ID"],
  "type": "user"
}
```

### Event Types

| Event | Trigger |
|-------|---------|
| `trade` | Trade lifecycle: MATCHED, MINED, CONFIRMED, RETRYING, FAILED |
| `order` | Order lifecycle: PLACEMENT, UPDATE, CANCELLATION |

### Trade Message

```json
{
  "event_type": "trade",
  "id": "trade-uuid",
  "market": "0xCONDITION_ID",
  "asset_id": "TOKEN_ID",
  "side": "BUY",
  "size": "10",
  "price": "0.57",
  "status": "MATCHED",
  "maker_orders": [{ "order_id": "0x...", "matched_amount": "10", "price": "0.57" }],
  "type": "TRADE"
}
```

### Order Message

```json
{
  "event_type": "order",
  "id": "0xORDER_ID",
  "market": "0xCONDITION_ID",
  "asset_id": "TOKEN_ID",
  "side": "SELL",
  "price": "0.57",
  "original_size": "10",
  "size_matched": "0",
  "type": "PLACEMENT"
}
```

Order types: `PLACEMENT`, `UPDATE` (partial fill), `CANCELLATION`.

## Sports Channel

No subscription message needed. Connect and receive all active sports data.

```json
// sport_result
{ "type": "sport_result", ... }  // Live scores, periods, status
```

## Dynamic Subscribe / Unsubscribe

Modify subscriptions without reconnecting:

```json
// Market channel — subscribe to more
{ "assets_ids": ["NEW_TOKEN_ID"], "operation": "subscribe", "custom_feature_enabled": true }

// Market channel — unsubscribe
{ "assets_ids": ["OLD_TOKEN_ID"], "operation": "unsubscribe" }

// User channel — subscribe to more markets
{ "markets": ["0xNEW_CONDITION_ID"], "operation": "subscribe" }
```

## Heartbeat

### Market & User Channels
Send `PING` every **10 seconds**. Server responds with `PONG`.

```typescript
const ws = new WebSocket("wss://ws-subscriptions-clob.polymarket.com/ws/market");

ws.onopen = () => {
  // Subscribe...
  setInterval(() => ws.send("PING"), 10_000);
};

ws.onmessage = (event) => {
  if (event.data === "PONG") return;
  const msg = JSON.parse(event.data);
  // handle msg.event_type
};
```

### Sports Channel
Server sends `ping` every 5 seconds. Respond with `pong` within 10 seconds or connection closes.

## Full TypeScript Example

```typescript
const ws = new WebSocket("wss://ws-subscriptions-clob.polymarket.com/ws/market");

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "market",
    assets_ids: ["TOKEN_ID"],
    custom_feature_enabled: true,
  }));
  setInterval(() => ws.send("PING"), 10_000);
};

ws.onmessage = (event) => {
  if (event.data === "PONG") return;
  const msg = JSON.parse(event.data);
  switch (msg.event_type) {
    case "book":
      console.log("Book snapshot:", msg.bids.length, "bids", msg.asks.length, "asks");
      break;
    case "price_change":
      for (const pc of msg.price_changes) {
        console.log(`${pc.side} ${pc.size}@${pc.price} (best: ${pc.best_bid}/${pc.best_ask})`);
      }
      break;
    case "last_trade_price":
      console.log(`Trade: ${msg.side} ${msg.size}@${msg.price}`);
      break;
    case "tick_size_change":
      console.log(`Tick: ${msg.old_tick_size} → ${msg.new_tick_size}`);
      break;
  }
};
```

## Troubleshooting

- **Connection closes immediately**: send subscription message right after open
- **Drops after ~10s**: you're not sending PING heartbeats
- **No messages**: verify asset IDs are correct and markets are active
- **Auth failed (user channel)**: check API credentials haven't expired
