# Authentication

Polymarket uses two-level auth: **L1** (EIP-712 private key signing) to create credentials, **L2** (HMAC-SHA256 API key signing) to authenticate requests. Builder program adds a separate set of **builder headers** for order attribution and relayer access.

## L1 Authentication (Private Key)

L1 proves wallet ownership via EIP-712 signature. Used to create or derive API credentials.

### EIP-712 Domain

```typescript
const domain = {
  name: "ClobAuthDomain",
  version: "1",
  chainId: 137,
};

const types = {
  ClobAuth: [
    { name: "address", type: "address" },
    { name: "timestamp", type: "string" },
    { name: "nonce", type: "uint256" },
    { name: "message", type: "string" },
  ],
};

const value = {
  address: signingAddress,       // The signing address
  timestamp: ts,                 // The CLOB API server timestamp
  nonce: nonce,                  // The nonce used
  message: "This message attests that I control the given wallet",
};
```

### L1 Headers

| Header | Description |
|--------|-------------|
| `POLY_ADDRESS` | Polygon signer address |
| `POLY_SIGNATURE` | CLOB EIP-712 signature |
| `POLY_TIMESTAMP` | Current UNIX timestamp |
| `POLY_NONCE` | Nonce (default: 0) |

### Create / Derive Credentials

```typescript
// TypeScript
const client = new ClobClient("https://clob.polymarket.com", 137, signer);
const creds = await client.createOrDeriveApiKey();
// { apiKey: "uuid", secret: "base64...", passphrase: "string" }
```

```python
# Python
client = ClobClient("https://clob.polymarket.com", key=pk, chain_id=137)
creds = client.create_or_derive_api_creds()
```

**REST endpoints:**
- `POST {host}/auth/api-key` — create new credentials (requires L1 headers)
- `GET {host}/auth/derive-api-key` — derive existing credentials (requires L1 headers)

## L2 Authentication (API Key)

L2 uses HMAC-SHA256 signatures from the API credentials. Required for all `/v1/trade/*` endpoints.

### L2 Headers (all 5 required)

| Header | Description |
|--------|-------------|
| `POLY_ADDRESS` | Polygon signer address |
| `POLY_SIGNATURE` | HMAC signature for request |
| `POLY_TIMESTAMP` | Current UNIX timestamp |
| `POLY_API_KEY` | User's API `apiKey` value |
| `POLY_PASSPHRASE` | User's API `passphrase` value |

### Initialize Trading Client

```typescript
// TypeScript
const client = new ClobClient(
  "https://clob.polymarket.com",
  137,
  signer,
  apiCreds,       // { apiKey, secret, passphrase }
  2,              // signatureType
  funderAddress   // proxy wallet address
);
```

```python
# Python
client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=pk,
    creds=api_creds,
    signature_type=2,
    funder=funder_address,
)
```

## Signature Types

| Type | Value | When to Use |
|------|-------|-------------|
| EOA | `0` | Standard Ethereum wallet (MetaMask). Funder is the EOA address and will need POL to pay gas on transactions. |
| POLY_PROXY | `1` | A custom proxy wallet only used with users who logged in via Magic Link email/Google. Using this requires the user to have exported their PK from Polymarket.com and imported into your app. |
| GNOSIS_SAFE | `2` | Gnosis Safe multisig proxy wallet (most common). Use this for any new or returning user who does not fit the other 2 types. |

The **funder** is the address holding funds. For proxy wallets, find it at polymarket.com/settings. Proxy wallets are auto-deployed on first Polymarket.com login.

## Builder Headers

Builder authentication is separate from L1/L2. Used for order attribution and relayer access.

### Builder Headers (4 required)

| Header | Description |
|--------|-------------|
| `POLY_BUILDER_API_KEY` | Builder API key |
| `POLY_BUILDER_TIMESTAMP` | Unix timestamp |
| `POLY_BUILDER_PASSPHRASE` | Builder passphrase |
| `POLY_BUILDER_SIGNATURE` | HMAC-SHA256 of request |

### Initialize Client with Builder Config

```typescript
// TypeScript — local signing
import { BuilderConfig, BuilderApiKeyCreds } from "@polymarket/builder-signing-sdk";

const builderCreds: BuilderApiKeyCreds = {
  key: process.env.POLY_BUILDER_API_KEY!,
  secret: process.env.POLY_BUILDER_SECRET!,
  passphrase: process.env.POLY_BUILDER_PASSPHRASE!,
};

const builderConfig = new BuilderConfig({ localBuilderCreds: builderCreds });

const client = new ClobClient(
  "https://clob.polymarket.com",
  137,
  signer,
  apiCreds,
  2,
  funderAddress,
  undefined,
  false,
  builderConfig
);
// Orders automatically include builder headers
```

```python
# Python — local signing
from py_builder_signing_sdk import BuilderConfig, BuilderApiKeyCreds

builder_config = BuilderConfig(
    local_builder_creds=BuilderApiKeyCreds(
        key=os.environ["POLY_BUILDER_API_KEY"],
        secret=os.environ["POLY_BUILDER_SECRET"],
        passphrase=os.environ["POLY_BUILDER_PASSPHRASE"],
    )
)

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=pk,
    creds=api_creds,
    signature_type=2,
    funder=funder_address,
    builder_config=builder_config,
)
```

### Remote Signing

Keep builder credentials on a separate server. Client points to your signing endpoint:

```typescript
// TypeScript client
const builderConfig = new BuilderConfig({
  remoteBuilderConfig: { url: "https://your-server.com/sign" },
});
```

```python
# Python client
from py_builder_signing_sdk import BuilderConfig, RemoteBuilderConfig

builder_config = BuilderConfig(
    remote_builder_config=RemoteBuilderConfig(url="https://your-server.com/sign")
)
```

Your server receives `{ method, path, body }` and returns the 4 `POLY_BUILDER_*` headers.

## Credential Lifecycle

- **Create**: `client.createApiKey()` — generates new credentials with a nonce
- **Derive**: `client.deriveApiKey(nonce)` — recovers existing credentials if you know the nonce
- **Create or Derive**: `client.createOrDeriveApiKey()` — creates if first time, derives if existing
- **Revoke builder key**: `client.revokeBuilderApiKey()` — invalidate compromised builder credentials

Lost credentials + lost nonce = create fresh credentials. Save your nonce.
