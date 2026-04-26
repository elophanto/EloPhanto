# Gasless Transactions

Polymarket's **Relayer Client** enables gasless transactions. Instead of requiring users to hold POL, Polymarket's infrastructure pays gas fees. Users only need USDC.e to trade.

Requires **Builder Program** membership. You need Builder API credentials.

## How It Works

1. Your app creates a transaction
2. User signs it with their private key
3. App sends to Polymarket's relayer
4. Relayer submits onchain and pays gas
5. Transaction executes from the user's wallet

## What's Covered

| Operation | Description |
|-----------|-------------|
| Wallet deployment | Deploy Safe or Proxy wallets for new users |
| Token approvals | Approve contracts to spend USDC.e or outcome tokens |
| CTF operations | Split, merge, redeem positions |
| Transfers | Move tokens between addresses |

## Installation

```bash
# TypeScript
npm install @polymarket/builder-relayer-client @polymarket/builder-signing-sdk

# Python
pip install py-builder-relayer-client py-builder-signing-sdk
```

## Client Setup

### TypeScript (Local Signing)

```typescript
import { createWalletClient, http, Hex } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { polygon } from "viem/chains";
import { RelayClient } from "@polymarket/builder-relayer-client";
import { BuilderConfig } from "@polymarket/builder-signing-sdk";

const account = privateKeyToAccount(process.env.PRIVATE_KEY as Hex);
const wallet = createWalletClient({
  account,
  chain: polygon,
  transport: http(process.env.RPC_URL),
});

const builderConfig = new BuilderConfig({
  localBuilderCreds: {
    key: process.env.POLY_BUILDER_API_KEY!,
    secret: process.env.POLY_BUILDER_SECRET!,
    passphrase: process.env.POLY_BUILDER_PASSPHRASE!,
  },
});

const client = new RelayClient(
  "https://relayer-v2.polymarket.com/",
  137,
  wallet,
  builderConfig
);
```

### Python (Local Signing)

```python
import os
from py_builder_relayer_client.client import RelayClient
from py_builder_signing_sdk import BuilderConfig, BuilderApiKeyCreds

builder_config = BuilderConfig(
    local_builder_creds=BuilderApiKeyCreds(
        key=os.getenv("POLY_BUILDER_API_KEY"),
        secret=os.getenv("POLY_BUILDER_SECRET"),
        passphrase=os.getenv("POLY_BUILDER_PASSPHRASE"),
    )
)

client = RelayClient(
    "https://relayer-v2.polymarket.com",
    137,
    os.getenv("PRIVATE_KEY"),
    builder_config,
)
```

### Remote Signing

Keep credentials on your server. Client points to signing endpoint:

```typescript
// TypeScript
const builderConfig = new BuilderConfig({
  remoteBuilderConfig: { url: "https://your-server.com/sign" },
});

const client = new RelayClient(
  "https://relayer-v2.polymarket.com/",
  137,
  wallet,
  builderConfig
);
```

```python
# Python
from py_builder_signing_sdk import BuilderConfig, RemoteBuilderConfig

builder_config = BuilderConfig(
    remote_builder_config=RemoteBuilderConfig(url="https://your-server.com/sign")
)

client = RelayClient("https://relayer-v2.polymarket.com", 137, pk, builder_config)
```

## Wallet Types

| Type | Deployment | Best For |
|------|------------|----------|
| **Safe** | Call `deploy()` before first transaction | Most builder integrations |
| **Proxy** | Auto-deploys on first transaction | Magic Link users |

```typescript
// TypeScript — Safe wallet
import { RelayClient, RelayerTxType } from "@polymarket/builder-relayer-client";

const client = new RelayClient(
  "https://relayer-v2.polymarket.com/",
  137,
  wallet,
  builderConfig,
  RelayerTxType.SAFE
);

// Deploy before first transaction
const response = await client.deploy();
const result = await response.wait();
console.log("Safe Address:", result?.proxyAddress);
```

```python
# Python — Safe wallet
response = client.deploy()
result = response.wait()
print("Safe Address:", result.get("proxyAddress"))
```

## Executing Transactions

```typescript
interface Transaction {
  to: string;    // Target contract address
  data: string;  // Encoded function call
  value: string; // POL to send (usually "0")
}

const response = await client.execute(transactions, "Description");
const result = await response.wait();
```

### Token Approval Example

```typescript
import { encodeFunctionData, maxUint256 } from "viem";

const USDC = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174";
const CTF = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045";

const approveTx = {
  to: USDC,
  data: encodeFunctionData({
    abi: [{
      name: "approve", type: "function",
      inputs: [{ name: "spender", type: "address" }, { name: "amount", type: "uint256" }],
      outputs: [{ type: "bool" }],
    }],
    functionName: "approve",
    args: [CTF, maxUint256],
  }),
  value: "0",
};

const response = await client.execute([approveTx], "Approve USDC.e for CTF");
await response.wait();
```

### Batch Transactions

Execute multiple operations atomically in a single call:

```typescript
const response = await client.execute(
  [approveTx, transferTx],
  "Approve and transfer"
);
await response.wait();
```

## Transaction States

| State | Terminal | Description |
|-------|----------|-------------|
| `STATE_NEW` | No | Received by relayer |
| `STATE_EXECUTED` | No | Submitted onchain |
| `STATE_MINED` | No | Included in a block |
| `STATE_CONFIRMED` | Yes | Finalized successfully |
| `STATE_FAILED` | Yes | Failed permanently |
| `STATE_INVALID` | Yes | Rejected as invalid |

## Builder Setup

1. Go to polymarket.com/settings?tab=builder
2. Create builder profile + generate API keys
3. Implement builder signing in your CLOB client
4. All orders automatically attributed to your builder account

## Contract Addresses

| Contract | Address | Approval Needed |
|----------|---------|-----------------|
| USDC.e (Bridged USDC) | `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` | — |
| CTF | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` | USDC.e |
| CTF Exchange | `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` | USDC.e, Tokens |
| Neg Risk CTF Exchange | `0xC5d563A36AE78145C45a50134d48A1215220f80a` | USDC.e, Tokens |
| Neg Risk Adapter | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` | Tokens |

## SDKs

- [Builder Relayer Client (TypeScript)](https://github.com/Polymarket/builder-relayer-client)
- [Builder Relayer Client (Python)](https://github.com/Polymarket/py-builder-relayer-client)
- [Builder Signing SDK (TypeScript)](https://github.com/Polymarket/builder-signing-sdk)
- [Builder Signing SDK (Python)](https://github.com/Polymarket/py-builder-signing-sdk)
