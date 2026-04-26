# CTF Operations

The **Conditional Token Framework (CTF)** creates ERC1155 tokens for market outcomes. Three core operations: split, merge, redeem.

## Token Model

Every binary market has two tokens:

| Token | Redeems for | Condition |
|-------|-------------|-----------|
| **Yes** | $1.00 USDC.e | Event occurs |
| **No** | $1.00 USDC.e | Event does not occur |

Every Yes/No pair is backed by exactly $1.00 USDC.e locked in the CTF contract.

## Split

Convert USDC.e into a full set of outcome tokens.

```
$100 USDC.e → 100 Yes tokens + 100 No tokens
```

### Prerequisites
1. USDC.e balance on Polygon
2. USDC.e approval for CTF contract
3. Condition ID of the market (the condition must already be prepared on the CTF contract via `prepareCondition`)

### Function: `splitPosition`

| Parameter | Type | Value |
|-----------|------|-------|
| `collateralToken` | IERC20 | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (USDC.e) |
| `parentCollectionId` | bytes32 | `0x0000...0000` (32 zero bytes) |
| `conditionId` | bytes32 | Market's condition ID |
| `partition` | uint[] | `[1, 2]` for binary (Yes=1, No=2) |
| `amount` | uint256 | Amount of USDC.e to split |

## Merge

Convert a full set of outcome tokens back to USDC.e. Inverse of split.

```
100 Yes tokens + 100 No tokens → $100 USDC.e
```

### Prerequisites
1. Equal amounts of both Yes and No tokens
2. Condition ID (the condition must already be prepared on the CTF contract via `prepareCondition`)
3. Sufficient gas for the transaction

### Function: `mergePositions`

Same parameters as split. Burns one unit of each position per unit of collateral returned.

## Redeem

Exchange winning tokens for USDC.e after market resolution.

```
Market resolves YES:
  100 Yes tokens → $100 USDC.e
  100 No tokens  → $0
```

### Prerequisites
1. Market must be resolved
2. Hold winning tokens
3. Know the condition ID

### Function: `redeemPositions`

| Parameter | Type | Value |
|-----------|------|-------|
| `collateralToken` | IERC20 | USDC.e address |
| `parentCollectionId` | bytes32 | `0x0000...0000` |
| `conditionId` | bytes32 | Market's condition ID |
| `indexSets` | uint[] | `[1, 2]` — redeems both (only winner pays) |

Redemption burns your **entire** token balance for the condition — no amount parameter. No deadline — winning tokens are always redeemable.

### Payout Vectors

| Outcome | Payout Vector | Redemption |
|---------|---------------|------------|
| Yes wins | `[1, 0]` | Yes = $1, No = $0 |
| No wins | `[0, 1]` | Yes = $0, No = $1 |

## Contract Addresses

| Contract | Address | Purpose |
|----------|---------|---------|
| CTF | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` | Token storage and operations |
| USDC.e (Bridged USDC) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | Collateral token |
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` | Standard market trading |
| Neg Risk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` | Neg risk market trading |
| Neg Risk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` | Neg risk conversions |

## Approval Matrix

Before trading or CTF operations, the funder must approve the relevant contracts:

| Operation | Contract to Approve | Token |
|-----------|-------------------|-------|
| Buy order (standard) | CTF Exchange | USDC.e |
| Sell order (standard) | CTF Exchange | Conditional tokens |
| Buy order (neg risk) | Neg Risk CTF Exchange | USDC.e |
| Sell order (neg risk) | Neg Risk CTF Exchange | Conditional tokens |
| Split | CTF | USDC.e |
| Neg risk conversion | Neg Risk Adapter | Conditional tokens |

## Standard vs Neg Risk Markets

| Feature | Standard Markets | Neg Risk Markets |
|---------|-----------------|------------------|
| CTF Contract | ConditionalTokens | ConditionalTokens |
| Exchange Contract | CTF Exchange | Neg Risk CTF Exchange |
| Multi-outcome | Independent markets | Linked via conversion |
| `negRisk` flag | `false` | `true` |
| Order option | `negRisk: false` | `negRisk: true` |

## Negative Risk

Multi-outcome events where only one outcome can win. A No token in any market can be **converted** into 1 Yes token in every other market.

### Conversion Example

Event: "Who wins?" with outcomes Trump, Harris, Other.

| Outcome | Before | After Conversion |
|---------|--------|------------------|
| Trump | — | 1 Yes |
| Harris | — | 1 Yes |
| Other | 1 No | — |

Conversion is atomic through the Neg Risk Adapter contract.

### Identifying Neg Risk Markets

```json
{
  "negRisk": true   // on event or market object from API
}
```

When placing orders: pass `negRisk: true` in options.

## Augmented Negative Risk

For events where new outcomes emerge after trading begins (e.g., new candidate enters race).

| Outcome Type | Description |
|--------------|-------------|
| Named outcomes | Known outcomes (e.g., "Trump", "Harris") |
| Placeholder outcomes | Reserved slots clarified later (e.g., "Person A") |
| Explicit Other | Catches any unnamed outcome |

### Identifying

```json
{
  "enableNegRisk": true,
  "negRiskAugmented": true
}
```

### Rules
- Only trade on **named outcomes** — ignore placeholders
- If correct outcome is not named at resolution, market resolves to "Other"
- "Other" definition changes as placeholders are clarified — avoid trading it directly

## Token ID Computation

Token IDs are computed onchain in three steps:

1. `getConditionId(oracle, questionId, outcomeSlotCount)` — oracle = UMA CTF Adapter, outcomeSlotCount = 2 for binary
2. `getCollectionId(parentCollectionId, conditionId, indexSet)` — parentCollectionId = bytes32(0), indexSet = 1 (Yes) or 2 (No)
3. `getPositionId(collateralToken, collectionId)` — combines USDC.e contract address on Polygon with collection

In practice, get token IDs from the Markets API `tokens` array. Manual computation only needed for direct contract interaction.
