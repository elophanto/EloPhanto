# Bridge

Polymarket uses **USDC.e** (Bridged USDC) on Polygon as collateral. The Bridge API handles deposits from and withdrawals to multiple chains.

Base URL: `https://bridge.polymarket.com`

## Deposit Flow

1. `POST /deposit` with your Polymarket wallet address → get deposit addresses
2. Verify token is supported via `/supported-assets`
3. Send assets to the appropriate address for your source chain
4. Assets are bridged and auto-swapped to USDC.e on Polygon
5. Track status via `/status/{deposit_address}`

```bash
# Create deposit addresses
curl -X POST https://bridge.polymarket.com/deposit \
  -H "Content-Type: application/json" \
  -d '{"address": "0xYOUR_POLYMARKET_WALLET"}'
```

Response includes three address types:

| Address | Use For |
|---------|---------|
| `evm` | Ethereum, Arbitrum, Base, Optimism, and other EVM chains |
| `svm` | Solana |
| `btc` | Bitcoin |
| `tvm` | Tron |

Each address is unique to your wallet.

## Supported Chains

| Chain | Address Type | Min Deposit | Example Tokens |
|-------|--------------|-------------|----------------|
| Ethereum | EVM | $7 | ETH, USDC, USDT, WBTC, DAI, LINK, UNI, AAVE |
| Polygon | EVM | $2 | POL, USDC, USDT, DAI, WETH, SAND |
| Arbitrum | EVM | $2 | ETH, ARB, USDC, USDT, DAI, WBTC, USDe |
| Base | EVM | $2 | ETH, USDC, USDT, DAI, cbBTC, AERO, USDS |
| Optimism | EVM | $2 | ETH, OP, USDC, USDT, DAI, USDe |
| BNB Smart Chain | EVM | $2 | BNB, USDC, USDT, DAI, ETH, BTCB, BUSD |
| Solana | SVM | $2 | SOL, USDC, USDT, USDe, TRUMP |
| Bitcoin | BTC | $9 | BTC |
| Tron | TVM | $9 | USDT |
| HyperEVM | EVM | $2 | HYPE, USDC, USDe, stHYPE, UBTC, UETH |
| Abstract | EVM | $2 | ETH, USDC, USDT |
| Monad | EVM | $2 | MON, USDC, USDT |
| Ethereal | EVM | $2 | USDe, WUSDe |
| Katana | EVM | $2 | AUSD |
| Lighter | EVM | $2 | USDC |

Always call `/supported-assets` for the current list — assets change over time.

## Withdrawal Flow

1. Check destination chain/token via `/supported-assets`
2. Preview fees via `POST /quote`
3. `POST /withdraw` with wallet address, destination chain, token, and recipient → get deposit addresses
4. Send USDC.e from Polymarket wallet to the appropriate address
5. Track status via `/status/{address}`

```bash
# Create withdrawal addresses
curl -X POST https://bridge.polymarket.com/withdraw \
  -H "Content-Type: application/json" \
  -d '{
    "address": "0xYOUR_POLYMARKET_WALLET",
    "toChainId": "1",
    "toTokenAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "recipientAddr": "0xDESTINATION_ADDRESS"
  }'
```

**Do not pre-generate withdrawal addresses.** Generate them only when ready to execute.

## Quote

Preview fees and estimated output for deposits and withdrawals. Withdrawals are **instant** and **free** — Polymarket does not charge withdrawal fees.

```bash
POST https://bridge.polymarket.com/quote
```

## Status Tracking

```bash
# Use the deposit address (not your wallet address)
curl https://bridge.polymarket.com/status/0xDEPOSIT_ADDRESS
```

### Transaction Statuses

| Status | Terminal | Description |
|--------|----------|-------------|
| `DEPOSIT_DETECTED` | No | Funds detected on source chain, not yet processing |
| `PROCESSING` | No | Being routed and swapped |
| `ORIGIN_TX_CONFIRMED` | No | Source chain transaction confirmed |
| `SUBMITTED` | No | Submitted to Polygon |
| `COMPLETED` | Yes | Funds arrived — success |
| `FAILED` | Yes | Error occurred |

Poll every 10–30 seconds until `COMPLETED` or `FAILED`.

### Response

```json
{
  "transactions": [{
    "fromChainId": "1",
    "fromTokenAddress": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "fromAmountBaseUnit": "1000000000",
    "toChainId": "137",
    "toTokenAddress": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "status": "COMPLETED",
    "txHash": "0x...",
    "createdTimeMs": 1697875200000
  }]
}
```

Empty `transactions` array = no deposits detected yet.

## Recovery

If you deposited the wrong token:
- **Ethereum deposits**: https://recovery.polymarket.com/
- **Polygon deposits**: https://matic-recovery.polymarket.com/

Sending unsupported tokens may cause **irrecoverable loss**.

## Caveats

- **Withdrawals >$50,000**: break into smaller amounts to minimize slippage
- **Uniswap pool exhaustion**: USDC.e → USDC swap goes through Uniswap v3 pool. If pool is exhausted, use smaller amounts or wait for rebalance
- **Deposits below minimum**: will not be processed
- **Supported assets change**: always check `/supported-assets` before depositing
