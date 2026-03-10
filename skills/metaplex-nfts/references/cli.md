# Metaplex CLI Reference

## Installation

```bash
npm install -g @metaplex-foundation/cli
```

## Command Discovery

```bash
mplx --help                    # List all topics
mplx <topic> --help            # e.g., mplx core --help
mplx <topic> <cmd> --help      # e.g., mplx core asset create --help
```

Topics: `config`, `toolbox`, `core`, `tm`, `cm`, `bg`

---

## Quick Command Index

| Topic | Detail File |
|-------|-------------|
| Core Assets/Collections | `./cli-core.md` |
| Token Metadata NFTs/pNFTs | `./cli-token-metadata.md` |
| Bubblegum (compressed NFTs) | `./cli-bubblegum.md` |
| Candy Machine (NFT drops) | `./cli-candy-machine.md` |
| Config, Storage, SOL, Tokens | Below |

---

## Shared Commands

```bash
# Config
mplx config                              # Show all config
mplx config get <KEY>                    # KEY: rpcUrl|commitment|payer|keypair
mplx config set <KEY> <VALUE>

# Storage
mplx toolbox storage upload <PATH>
mplx toolbox storage upload <PATH> --directory    # Multiple files at once
mplx toolbox storage balance                      # Check Irys balance
mplx toolbox storage fund <AMOUNT>                # Fund Irys account
mplx toolbox storage withdraw <AMOUNT>            # Withdraw from Irys

# SOL
mplx toolbox sol balance
mplx toolbox sol airdrop --amount <NUM>
mplx toolbox sol transfer <DESTINATION> <AMOUNT>
mplx toolbox sol wrap <AMOUNT>                    # SOL -> wSOL
mplx toolbox sol unwrap                           # wSOL -> SOL

# Tokens (fungible)
mplx toolbox token create --wizard                                          # Interactive (recommended)
mplx toolbox token create --name <NAME> --symbol <SYM> --decimals <NUM> --image <PATH>
mplx toolbox token create --name <NAME> --symbol <SYM> --decimals <NUM> --image <PATH> --mint-amount <NUM>
mplx toolbox token create --name <NAME> --symbol <SYM> --decimals <NUM> --image <PATH> --description <DESC>
mplx toolbox token mint <MINT_ADDRESS> <AMOUNT>                             # Mint more tokens
mplx toolbox token mint <MINT_ADDRESS> <AMOUNT> --recipient <ADDR>          # Mint to another wallet
mplx toolbox token transfer <MINT> <AMOUNT> <DESTINATION>
mplx toolbox token update <MINT> --name <NAME>                              # Update metadata
mplx toolbox token add-metadata <MINT> --name <NAME> --symbol <SYM> --image <PATH>  # Add metadata to existing mint
```

**Notes:**
- `mplx toolbox token create` requires a local `--image` file — it does NOT accept `--uri`. The CLI handles upload to Irys automatically, so this command requires Irys storage access and will not work on localnet/localhost.
- `--mint-amount`, `mplx toolbox token mint`, and `mplx toolbox token transfer` amounts are all in **base units** (smallest denomination). E.g., with 9 decimals, `--mint-amount 1000000000` mints 1 token. Tokens are minted to the payer wallet by default (use `mplx toolbox token mint <MINT> <AMOUNT> --recipient <ADDR>` for another wallet).
- `--decimals 9` is the standard for Solana tokens. Use 9 unless the user specifies otherwise.
- `mplx toolbox token mint` and `mplx toolbox token transfer` may fail on localnet if the mpl-toolbox program is not deployed. On localnet, use `spl-token mint` and `spl-token transfer` as fallbacks.

---

## Wizard Mode

Several commands support `--wizard` for interactive guided creation:

| Command | Wizard |
|---------|--------|
| `mplx toolbox token create --wizard` | Token name, symbol, decimals, image, mint amount |
| `mplx tm create --wizard` | NFT type, metadata, collection, royalties |
| `mplx bg tree create --wizard` | Tree depth, buffer size, canopy |
| `mplx bg nft create --wizard` | cNFT metadata, tree selection, collection |
| `mplx cm create --wizard` | Full candy machine setup, upload, and insert |

Wizards are recommended for first-time operations or when unsure about required parameters.

> **Agent note**: Wizards are interactive (require user input at prompts). When running programmatically or as an agent, prefer explicit flags instead of `--wizard`.

---

## Local Files Workflow (`--files`)

Some commands can upload files and create assets in one step, as an alternative to manual upload -> create:

```bash
# Core asset from local files (uploads image + JSON, then creates)
mplx core asset create --files --image ./image.png --json ./metadata.json

# TM NFT from local files (no --files flag needed for tm)
mplx tm create --image ./image.png --json ./metadata.json

# Fungible token always uses local image (no --files flag needed)
mplx toolbox token create --name "My Token" --symbol "MTK" --decimals 9 --image ./image.png
```

If `--files` fails (e.g., upload timeout), fall back to the manual workflow:
1. `mplx toolbox storage upload <PATH>` to upload separately
2. Then create with `--uri` pointing to the uploaded URI

---

## Initial Setup

Run all checks in one command:

```bash
mplx config get rpcUrl && mplx config get keypair && mplx toolbox sol balance
```

**Error Resolution:**

| Error | Fix |
|-------|-----|
| `mplx: command not found` | `npm i -g @metaplex-foundation/cli` |
| `No RPC URL configured` | `mplx config set rpcUrl https://api.devnet.solana.com` |
| `No keypair configured` | `mplx config set keypair ~/.config/solana/id.json` |
| `0 SOL` | `mplx toolbox sol airdrop --amount 2` (devnet only) |

**Mainnet Safety:** If RPC URL contains `mainnet`, confirm with user before executing commands that spend SOL.

---

## Storage Management

```bash
# Check Irys balance before large uploads
mplx toolbox storage balance

# Fund Irys account if balance is insufficient
mplx toolbox storage fund 0.1

# Withdraw unused funds
mplx toolbox storage withdraw 0.05
```

---

## Batching Principle

> **CRITICAL**: Always chain commands with `&&` to minimize user approvals. One approval per logical step.

```bash
# Setup checks - ONE command
mplx config get rpcUrl && mplx config get keypair && mplx toolbox sol balance

# File creation - ONE command
echo '{"name": "NFT #1", ...}' > meta/1.json && \
echo '{"name": "NFT #2", ...}' > meta/2.json && \
echo '{"name": "NFT #3", ...}' > meta/3.json

# Uploads - use --directory for folders
mplx toolbox storage upload ./assets --directory

# Multiple asset creates - ONE command
mplx core asset create --name "NFT #1" --uri "<URI_1>" --collection <ADDR> && \
mplx core asset create --name "NFT #2" --uri "<URI_2>" --collection <ADDR> && \
mplx core asset create --name "NFT #3" --uri "<URI_3>" --collection <ADDR>
```

**NEVER** run multiple uploads or creates as separate commands - that requires one approval per command.

---

## Explorer Links

```
# Core assets/collections
https://core.metaplex.com/explorer/<ADDRESS>?env=devnet    # Devnet
https://core.metaplex.com/explorer/<ADDRESS>               # Mainnet

# Token Metadata NFTs / Tokens
https://explorer.solana.com/address/<MINT_ADDRESS>?cluster=devnet  # Devnet
https://explorer.solana.com/address/<MINT_ADDRESS>                 # Mainnet

# Transactions
https://explorer.solana.com/tx/<SIGNATURE>?cluster=devnet  # Devnet
https://explorer.solana.com/tx/<SIGNATURE>                 # Mainnet
```

> **IMPORTANT**: Always add `?env=devnet` or `?cluster=devnet` when on devnet.

> **Localnet note**: The CLI generates devnet explorer links even when connected to localhost. For localnet, use Solana Explorer with a custom cluster URL: `https://explorer.solana.com/address/<ADDRESS>?cluster=custom&customUrl=http://localhost:8899`

---

## Localnet Limitations

When running on localhost/localnet, several CLI features are unavailable or require workarounds:

- **Storage uploads (Irys) do not work on localhost.** Any command that uploads to Irys will fail.
- **Commands using `--image` without `--uri` will fail** because they attempt to upload to Irys under the hood. This affects `mplx toolbox token create`, `mplx core asset create --files`, and `mplx tm create --image`.
- **For localnet, always use `--uri`** with any URL (even a placeholder) for create commands: `mplx core asset create --name "Test" --uri "https://example.com/meta.json"`
- **For fungible tokens on localnet**, use the SPL Token CLI and then attach metadata:
  ```bash
  spl-token create-token
  # Note the mint address, then:
  mplx toolbox token add-metadata <MINT> --name <NAME> --symbol <SYM> --uri <URI>
  ```
- **`mplx core asset update` and `mplx tm update`** also require Irys if re-uploading metadata (e.g., updating `--image`). On localnet, only update fields that do not trigger an upload (e.g., `--name`, `--uri` with a pre-existing URL).
- **`mplx toolbox token mint` and `mplx toolbox token transfer`** may fail if the mpl-toolbox program is not deployed on your localnet. Use `spl-token mint` and `spl-token transfer` as fallbacks.

---

## Troubleshooting

| Error | Solution |
|-------|----------|
| `InvalidTokenStandard` | Check asset's actual token standard |
| `InvalidAuthority` | Verify update/mint authority matches signer |
| `CollectionNotVerified` | Call `verifyCollectionV1` (TM collections need verification) |
| `PluginNotFound` | Add plugin first or check type name spelling |
| `InsufficientFunds` | Fund wallet with more SOL |
| `Invalid data enum variant` | Check plugin JSON format (array, correct types) |
| Upload fails / timeout | Check `mplx toolbox storage balance`, fund if needed |
