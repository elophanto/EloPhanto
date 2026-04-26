# Market Data

Four sources for market data: **Gamma API** (events, markets, search), **Data API** (trades, positions, user data), **CLOB** (orderbook, prices), and **Subgraph** (onchain queries).

## Gamma API

Base URL: `https://gamma-api.polymarket.com` — no auth required.

### Events Endpoint

```bash
# All active events
GET https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100

# By slug (from polymarket.com/event/{slug})
GET https://gamma-api.polymarket.com/events?slug=fed-decision-in-october

# By tag
GET https://gamma-api.polymarket.com/events?tag_id=100381&limit=10&active=true&closed=false

# By series (sports)
GET https://gamma-api.polymarket.com/events?series_id=10345&active=true&closed=false

# Sorted by volume
GET https://gamma-api.polymarket.com/events?active=true&closed=false&order=volume_24hr&ascending=false&limit=100
```

### Markets Endpoint

```bash
# By slug
GET https://gamma-api.polymarket.com/markets?slug=fed-decision-in-october
```

### Sort Parameters

| Parameter | Values |
|-----------|--------|
| `order` | `volume_24hr`, `volume`, `liquidity`, `start_date`, `end_date`, `competitive`, `closed_time` |
| `ascending` | `true` / `false` (default: `false`) |
| `active` | `true` / `false` |
| `closed` | `true` / `false` |
| `limit` | 1–500 (default: 20) |
| `offset` | Pagination offset |

### Pagination

```bash
# Page 1
GET https://gamma-api.polymarket.com/events?active=true&closed=false&limit=50&offset=0

# Page 2
GET https://gamma-api.polymarket.com/events?active=true&closed=false&limit=50&offset=50
```

Response includes `has_more: true/false`. Increment offset by limit until `has_more` is `false`.

### Tags & Sports

```bash
# Discover tags
GET https://gamma-api.polymarket.com/tags

# Sports metadata
GET https://gamma-api.polymarket.com/sports
```

## Data API

Base URL: `https://data-api.polymarket.com` — no auth required. Used for trades, positions, and user-specific data.

## CLOB Orderbook

Base URL: `https://clob.polymarket.com` — no auth for read endpoints.

### Get Orderbook

```typescript
// TypeScript
const client = new ClobClient("https://clob.polymarket.com", 137);
const book = await client.getOrderBook("TOKEN_ID");
// { bids: [{price, size}...], asks: [{price, size}...], tick_size, min_order_size, neg_risk }
```

```python
# Python
client = ClobClient("https://clob.polymarket.com", chain_id=137)
book = client.get_order_book("TOKEN_ID")
```

```bash
# REST
curl "https://clob.polymarket.com/book?token_id=TOKEN_ID"
```

### Prices

```typescript
const buyPrice = await client.getPrice("TOKEN_ID", "BUY");   // best ask
const sellPrice = await client.getPrice("TOKEN_ID", "SELL");  // best bid
```

```bash
curl "https://clob.polymarket.com/price?token_id=TOKEN_ID&side=BUY"
```

### Midpoint

```typescript
const mid = await client.getMidpoint("TOKEN_ID");  // { mid: "0.50" }
```

If bid-ask spread > $0.10, Polymarket UI shows last traded price instead of midpoint.

### Spread

```typescript
const spread = await client.getSpread("TOKEN_ID");  // { spread: "0.04" }
```

### Last Trade Price

```typescript
const last = await client.getLastTradePrice("TOKEN_ID");  // { price, side }
```

### Price History

```typescript
const history = await client.getPricesHistory({
  market: "TOKEN_ID",
  interval: PriceHistoryInterval.ONE_DAY,
  fidelity: 60,  // data points every 60 minutes
});
// Each entry: { t: timestamp, p: price }
```

| Interval | Description |
|----------|-------------|
| `1h` | Last hour |
| `6h` | Last 6 hours |
| `1d` | Last day |
| `1w` | Last week |
| `1m` | Last month |
| `max` | All available |

Use `startTs`/`endTs` for absolute ranges (mutually exclusive with `interval`).

### Estimate Fill Price

Walk the orderbook to estimate slippage for a given order size:

```typescript
const price = await client.calculateMarketPrice(
  "TOKEN_ID", Side.BUY, 500, OrderType.FOK
);
```

### Batch Requests

All orderbook queries have batch variants (up to 500 tokens):

| Single | Batch | REST |
|--------|-------|------|
| `getOrderBook()` | `getOrderBooks()` | `POST /books` |
| `getPrice()` | `getPrices()` | `POST /prices` |
| `getMidpoint()` | `getMidpoints()` | `POST /midpoints` |
| `getSpread()` | `getSpreads()` | `POST /spreads` |
| `getLastTradePrice()` | `getLastTradesPrices()` | — |

```typescript
const prices = await client.getPrices([
  { token_id: "TOKEN_A", side: Side.BUY },
  { token_id: "TOKEN_B", side: Side.BUY },
]);
```

## Key Market Fields

| Field | Description |
|-------|-------------|
| `tokenID` / `asset_id` | ERC1155 token ID for an outcome |
| `conditionID` / `market` | Condition ID — identifies the market |
| `questionID` | Hash of UMA ancillary data |
| `neg_risk` | `true` for multi-outcome events |
| `minimum_tick_size` | Minimum price increment |
| `enableOrderBook` | Whether orderbook is active |
| `slug` | URL-friendly identifier |
| `tokens` | Array of `{ token_id, outcome }` for both outcomes |

## Subgraph (Onchain Data)

GraphQL queries via Goldsky-hosted subgraphs:

| Subgraph | Description |
|----------|-------------|
| Positions | User token balances |
| Orders | Order book and trade events |
| Activity | Splits, merges, redemptions |
| Open Interest | Market and global OI |
| PNL | User position P&L |

```bash
curl -X POST \
  https://api.goldsky.com/api/public/project_cl6mb8i9h0003e201j6li0diw/subgraphs/orderbook-subgraph/0.0.1/gn \
  -H "Content-Type: application/json" \
  -d '{"query": "query { orderbooks { id tradesQuantity } }"}'
```

## Fetching Strategy

1. **Specific market**: fetch by slug — `GET https://gamma-api.polymarket.com/events?slug=...`
2. **Category browsing**: filter by tag — `GET https://gamma-api.polymarket.com/events?tag_id=...`
3. **All active markets**: paginate events — `GET https://gamma-api.polymarket.com/events?active=true&closed=false`
4. **Always include** `active=true&closed=false` unless you need historical data
5. **Events > Markets**: events contain their markets, reducing API calls
