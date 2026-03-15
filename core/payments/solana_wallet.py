"""SolanaWalletProvider — self-custody wallet using solders + solana-py.

Stores the private key encrypted in the EloPhanto vault.
Supports native SOL transfers, SPL token transfers (USDC), and
DEX swaps via Jupiter Ultra API on Solana.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Well-known Solana chain configuration
_SOLANA_CHAIN_CONFIG: dict[str, dict[str, Any]] = {
    "solana": {
        "rpc_url": "https://api.mainnet-beta.solana.com",
        "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    },
    "solana-devnet": {
        "rpc_url": "https://api.devnet.solana.com",
        "usdc": "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
    },
}

# Token decimals
_SOLANA_TOKEN_DECIMALS: dict[str, int] = {
    "sol": 9,
    "usdc": 6,
    "usdt": 6,
}

# Well-known token mint addresses (mainnet) for Jupiter swaps
_SOLANA_TOKEN_MINTS: dict[str, str] = {
    "sol": "So11111111111111111111111111111111111111112",
    "usdc": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "usdt": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

_JUPITER_BASE_URL = "https://api.jup.ag"

# SPL Token Program ID
_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
_ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
_SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"


class SolanaWalletProvider:
    """Local self-custody Solana wallet — auto-creates keypair.

    Uses solders for key generation/signing and JSON-RPC calls
    via urllib for on-chain operations. No external API keys needed.
    """

    def __init__(
        self, vault: Any, chain: str = "solana", rpc_url: str | None = None
    ) -> None:
        self._vault = vault
        self._chain = chain
        self._keypair: Any = None  # solders.Keypair

        chain_cfg = _SOLANA_CHAIN_CONFIG.get(chain, _SOLANA_CHAIN_CONFIG["solana"])
        self._rpc_url: str = rpc_url or chain_cfg["rpc_url"]
        self._usdc_mint: str = chain_cfg.get("usdc", "")

        self._load_or_create_keypair()

    # ------------------------------------------------------------------
    # Keypair lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_keypair(self) -> None:
        """Load existing keypair from vault or generate a new one."""
        from solders.keypair import Keypair  # type: ignore[import-untyped]

        stored_key = self._vault.get("solana_wallet_private_key")
        if stored_key:
            # Stored as base58 secret key (64 bytes = secret + public)
            import base58

            key_bytes = base58.b58decode(stored_key)
            self._keypair = Keypair.from_bytes(key_bytes)
            logger.info(f"Loaded Solana wallet: {self._keypair.pubkey()}")
        else:
            self._keypair = Keypair()
            # Store as base58-encoded 64-byte secret key
            import base58

            secret_b58 = base58.b58encode(bytes(self._keypair)).decode("ascii")
            self._vault.set("solana_wallet_private_key", secret_b58)
            self._vault.set("solana_wallet_address", str(self._keypair.pubkey()))
            self._vault.set("crypto_wallet_address", str(self._keypair.pubkey()))
            logger.info(f"Created Solana wallet: {self._keypair.pubkey()}")

    # ------------------------------------------------------------------
    # Public interface (matches LocalWalletProvider pattern)
    # ------------------------------------------------------------------

    def get_wallet_details(self) -> dict[str, Any]:
        """Return wallet address and chain info."""
        return {
            "address": str(self._keypair.pubkey()),
            "chain": self._chain,
            "provider": "local",
        }

    def get_address(self) -> str:
        """Return the wallet address (public key)."""
        return str(self._keypair.pubkey())

    def get_balance(self) -> str:
        """Get native SOL balance as a decimal string."""
        result = self._rpc_call("getBalance", [self.get_address()])
        lamports = result.get("value", 0) if isinstance(result, dict) else 0
        return str(lamports / 10**9)

    def get_spl_balance(self, mint_address: str) -> str:
        """Get SPL token balance for this wallet."""
        ata = self._get_associated_token_address(self.get_address(), mint_address)
        try:
            result = self._rpc_call(
                "getTokenAccountBalance",
                [ata],
            )
            value = result.get("value", {}) if isinstance(result, dict) else {}
            return value.get("uiAmountString", "0")
        except RuntimeError:
            # Token account doesn't exist = zero balance
            return "0"

    def get_erc20_balance(self, token_address: str) -> str:
        """Compatibility alias for SPL balance (matches EVM interface)."""
        return self.get_spl_balance(token_address)

    def native_transfer(self, to: str, amount: str) -> str:
        """Send native SOL. Returns transaction signature."""
        from solders.hash import Hash  # type: ignore[import-untyped]
        from solders.message import Message  # type: ignore[import-untyped]
        from solders.pubkey import Pubkey  # type: ignore[import-untyped]
        from solders.system_program import TransferParams, transfer  # type: ignore[import-untyped]
        from solders.transaction import Transaction  # type: ignore[import-untyped]

        lamports = int(float(amount) * 10**9)
        to_pubkey = Pubkey.from_string(to)

        # Build transfer instruction
        ix = transfer(
            TransferParams(
                from_pubkey=self._keypair.pubkey(),
                to_pubkey=to_pubkey,
                lamports=lamports,
            )
        )

        # Get recent blockhash
        blockhash_resp = self._rpc_call("getLatestBlockhash", [])
        blockhash_str = blockhash_resp.get("value", {}).get("blockhash", "")
        if not blockhash_str:
            raise RuntimeError("Failed to get recent blockhash")
        recent_blockhash = Hash.from_string(blockhash_str)

        # Build, sign, and send transaction
        msg = Message.new_with_blockhash([ix], self._keypair.pubkey(), recent_blockhash)
        tx = Transaction.new_unsigned(msg)
        tx.sign([self._keypair], recent_blockhash)

        # Serialize and send
        tx_bytes = bytes(tx)
        import base64

        tx_b64 = base64.b64encode(tx_bytes).decode("ascii")
        sig = self._rpc_call(
            "sendTransaction",
            [tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed"}],
        )
        logger.info(f"SOL transfer sent: {sig}")
        return str(sig)

    def transfer(self, to: str, amount: str, token: str = "USDC") -> str:
        """Send SPL tokens. Returns transaction signature."""
        import base64

        from solders.hash import Hash  # type: ignore[import-untyped]
        from solders.instruction import AccountMeta, Instruction  # type: ignore[import-untyped]
        from solders.message import Message  # type: ignore[import-untyped]
        from solders.pubkey import Pubkey  # type: ignore[import-untyped]
        from solders.transaction import Transaction  # type: ignore[import-untyped]

        mint_address = self._get_token_address(token)
        mint_pubkey = Pubkey.from_string(mint_address)
        to_pubkey = Pubkey.from_string(to)
        decimals = self._get_token_decimals(token)
        raw_amount = int(float(amount) * 10**decimals)

        # Get associated token accounts
        source_ata = self._get_associated_token_address(
            self.get_address(), mint_address
        )
        dest_ata = self._get_associated_token_address(to, mint_address)

        token_program = Pubkey.from_string(_TOKEN_PROGRAM_ID)
        ata_program = Pubkey.from_string(_ASSOCIATED_TOKEN_PROGRAM_ID)
        system_program = Pubkey.from_string(_SYSTEM_PROGRAM_ID)
        source_ata_pubkey = Pubkey.from_string(source_ata)
        dest_ata_pubkey = Pubkey.from_string(dest_ata)

        instructions = []

        # Check if destination ATA exists; if not, create it
        dest_info = self._rpc_call("getAccountInfo", [dest_ata, {"encoding": "base64"}])
        dest_value = dest_info.get("value") if isinstance(dest_info, dict) else None
        if dest_value is None:
            # Create associated token account instruction
            create_ata_ix = Instruction(
                program_id=ata_program,
                accounts=[
                    AccountMeta(
                        pubkey=self._keypair.pubkey(), is_signer=True, is_writable=True
                    ),
                    AccountMeta(
                        pubkey=dest_ata_pubkey, is_signer=False, is_writable=True
                    ),
                    AccountMeta(pubkey=to_pubkey, is_signer=False, is_writable=False),
                    AccountMeta(pubkey=mint_pubkey, is_signer=False, is_writable=False),
                    AccountMeta(
                        pubkey=system_program, is_signer=False, is_writable=False
                    ),
                    AccountMeta(
                        pubkey=token_program, is_signer=False, is_writable=False
                    ),
                ],
                data=b"",
            )
            instructions.append(create_ata_ix)

        # SPL Token transfer instruction (Transfer = instruction type 3)
        # Data: [3] + amount as little-endian u64
        transfer_data = bytes([3]) + raw_amount.to_bytes(8, "little")
        transfer_ix = Instruction(
            program_id=token_program,
            accounts=[
                AccountMeta(
                    pubkey=source_ata_pubkey, is_signer=False, is_writable=True
                ),
                AccountMeta(pubkey=dest_ata_pubkey, is_signer=False, is_writable=True),
                AccountMeta(
                    pubkey=self._keypair.pubkey(), is_signer=True, is_writable=False
                ),
            ],
            data=transfer_data,
        )
        instructions.append(transfer_ix)

        # Get recent blockhash
        blockhash_resp = self._rpc_call("getLatestBlockhash", [])
        blockhash_str = blockhash_resp.get("value", {}).get("blockhash", "")
        if not blockhash_str:
            raise RuntimeError("Failed to get recent blockhash")
        recent_blockhash = Hash.from_string(blockhash_str)

        # Build, sign, send
        msg = Message.new_with_blockhash(
            instructions, self._keypair.pubkey(), recent_blockhash
        )
        tx = Transaction.new_unsigned(msg)
        tx.sign([self._keypair], recent_blockhash)

        tx_bytes = bytes(tx)
        tx_b64 = base64.b64encode(tx_bytes).decode("ascii")
        sig = self._rpc_call(
            "sendTransaction",
            [tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed"}],
        )
        logger.info(f"SPL transfer sent: {sig}")
        return str(sig)

    def get_private_key_base58(self) -> str:
        """Return the private key as base58 string for owner export."""
        import base58

        return base58.b58encode(bytes(self._keypair)).decode("ascii")

    def supports_swap(self) -> bool:
        """Solana wallet supports DEX swaps via Jupiter Ultra API."""
        return True

    # ------------------------------------------------------------------
    # Jupiter Ultra API — DEX swaps
    # ------------------------------------------------------------------

    def jupiter_quote(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        api_key: str,
    ) -> dict[str, Any]:
        """Get a swap quote from Jupiter Ultra API without executing.

        Returns the order response including inAmount, outAmount, and price info.
        """
        input_mint = self._resolve_mint(from_token)
        output_mint = self._resolve_mint(to_token)
        decimals = _SOLANA_TOKEN_DECIMALS.get(from_token.lower(), 9)
        raw_amount = int(amount * 10**decimals)

        url = (
            f"{_JUPITER_BASE_URL}/ultra/v1/order"
            f"?inputMint={input_mint}"
            f"&outputMint={output_mint}"
            f"&amount={raw_amount}"
            f"&taker={self.get_address()}"
        )
        data = self._jupiter_request("GET", url, api_key=api_key)

        # Parse human-readable amounts
        out_decimals = _SOLANA_TOKEN_DECIMALS.get(to_token.lower(), 9)
        in_amount = int(data.get("inAmount", raw_amount)) / 10**decimals
        out_amount = int(data.get("outAmount", 0)) / 10**out_decimals

        return {
            "from_token": from_token.upper(),
            "to_token": to_token.upper(),
            "input_amount": in_amount,
            "output_amount": out_amount,
            "price": out_amount / in_amount if in_amount else 0,
            "request_id": data.get("requestId", ""),
        }

    def jupiter_swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        api_key: str,
    ) -> dict[str, Any]:
        """Execute a swap via Jupiter Ultra API.

        Flow: GET /ultra/v1/order → sign transaction → POST /ultra/v1/execute
        """
        import base64

        from solders.transaction import VersionedTransaction  # type: ignore[import-untyped]

        input_mint = self._resolve_mint(from_token)
        output_mint = self._resolve_mint(to_token)
        decimals = _SOLANA_TOKEN_DECIMALS.get(from_token.lower(), 9)
        raw_amount = int(amount * 10**decimals)

        # Step 1: Get order (unsigned transaction)
        order_url = (
            f"{_JUPITER_BASE_URL}/ultra/v1/order"
            f"?inputMint={input_mint}"
            f"&outputMint={output_mint}"
            f"&amount={raw_amount}"
            f"&taker={self.get_address()}"
        )
        order = self._jupiter_request("GET", order_url, api_key=api_key)

        tx_base64 = order.get("transaction")
        request_id = order.get("requestId")
        if not tx_base64 or not request_id:
            raise RuntimeError(
                f"Jupiter order failed: {order.get('error', 'no transaction returned')}"
            )

        # Step 2: Deserialize and sign the transaction
        tx_bytes = base64.b64decode(tx_base64)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        # solders VersionedTransaction is immutable; re-create with keypair to sign
        signed_tx = VersionedTransaction(tx.message, [self._keypair])
        signed_bytes = bytes(signed_tx)
        signed_b64 = base64.b64encode(signed_bytes).decode("ascii")

        # Step 3: Execute the signed transaction
        execute_url = f"{_JUPITER_BASE_URL}/ultra/v1/execute"
        result = self._jupiter_request(
            "POST",
            execute_url,
            api_key=api_key,
            body={
                "signedTransaction": signed_b64,
                "requestId": request_id,
            },
        )

        # Parse result
        out_decimals = _SOLANA_TOKEN_DECIMALS.get(to_token.lower(), 9)
        in_amount = int(order.get("inAmount", raw_amount)) / 10**decimals
        out_amount = int(order.get("outAmount", 0)) / 10**out_decimals
        tx_id = result.get("signature", result.get("transactionId", ""))

        logger.info(
            f"Jupiter swap executed: {in_amount} {from_token} → "
            f"{out_amount} {to_token} (tx: {tx_id})"
        )

        return {
            "tx_hash": tx_id,
            "from_token": from_token.upper(),
            "to_token": to_token.upper(),
            "input_amount": in_amount,
            "output_amount": out_amount,
            "request_id": request_id,
        }

    def _resolve_mint(self, symbol: str) -> str:
        """Resolve a token symbol or mint address to a mint address."""
        # If it looks like a mint address already, return as-is
        if len(symbol) > 20:
            return symbol
        mint = _SOLANA_TOKEN_MINTS.get(symbol.lower())
        if not mint:
            raise ValueError(
                f"Unknown token: {symbol}. Supported: "
                f"{', '.join(s.upper() for s in _SOLANA_TOKEN_MINTS)}. "
                f"Or pass a mint address directly."
            )
        return mint

    def _jupiter_request(
        self,
        method: str,
        url: str,
        api_key: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to Jupiter API."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "User-Agent": "EloPhanto/0.1",
        }

        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_data = json.loads(error_body)
                msg = error_data.get("error", error_data.get("message", error_body))
            except (json.JSONDecodeError, AttributeError):
                msg = error_body
            raise RuntimeError(f"Jupiter API error ({e.code}): {msg}") from e

        return result

    # ------------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------------

    def _rpc_call(self, method: str, params: list[Any]) -> Any:
        """Make a JSON-RPC call to the Solana RPC endpoint."""
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode("utf-8")

        req = urllib.request.Request(
            self._rpc_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "EloPhanto/0.1"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if "error" in data and data["error"]:
            msg = data["error"].get("message", str(data["error"]))
            raise RuntimeError(f"Solana RPC error: {msg}")
        return data.get("result")

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def _get_token_address(self, symbol: str) -> str:
        """Resolve token symbol to mint address on Solana."""
        tokens: dict[str, str] = {"usdc": self._usdc_mint}
        addr = tokens.get(symbol.lower())
        if not addr:
            raise ValueError(
                f"Unknown token: {symbol}. "
                f"Supported: {', '.join(t.upper() for t in tokens if tokens[t])}"
            )
        return addr

    @staticmethod
    def _get_token_decimals(symbol: str) -> int:
        """Get decimal places for a token symbol."""
        return _SOLANA_TOKEN_DECIMALS.get(symbol.lower(), 9)

    @staticmethod
    def _get_associated_token_address(owner: str, mint: str) -> str:
        """Derive the associated token account address for an owner + mint."""
        from solders.pubkey import Pubkey  # type: ignore[import-untyped]

        owner_pubkey = Pubkey.from_string(owner)
        mint_pubkey = Pubkey.from_string(mint)
        token_program = Pubkey.from_string(_TOKEN_PROGRAM_ID)
        ata_program = Pubkey.from_string(_ASSOCIATED_TOKEN_PROGRAM_ID)

        # PDA derivation: seeds = [owner, token_program, mint]
        ata, _bump = Pubkey.find_program_address(
            [bytes(owner_pubkey), bytes(token_program), bytes(mint_pubkey)],
            ata_program,
        )
        return str(ata)

    # ------------------------------------------------------------------
    # Incoming transaction scanning
    # ------------------------------------------------------------------

    def get_incoming_transactions(
        self,
        since_timestamp: float | None = None,
        token_filter: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch recent incoming transactions to this wallet.

        Uses getSignaturesForAddress + getTransaction to find transfers
        where this wallet received tokens/SOL.
        """
        address = self.get_address()
        sigs_result = self._rpc_call(
            "getSignaturesForAddress",
            [address, {"limit": limit}],
        )
        if not sigs_result:
            return []

        incoming: list[dict[str, Any]] = []
        for sig_info in sigs_result:
            if sig_info.get("err"):
                continue

            # Filter by timestamp
            block_time = sig_info.get("blockTime")
            if since_timestamp and block_time and block_time < since_timestamp:
                continue

            sig = sig_info["signature"]
            try:
                tx = self._rpc_call(
                    "getTransaction",
                    [
                        sig,
                        {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
                    ],
                )
            except Exception:
                continue

            if not tx or not tx.get("meta"):
                continue

            meta = tx["meta"]

            # Check SPL token transfers (postTokenBalances vs preTokenBalances)
            pre_tokens = {
                (b.get("accountIndex"), b.get("mint", "")): float(
                    b.get("uiTokenAmount", {}).get("uiAmount") or 0
                )
                for b in (meta.get("preTokenBalances") or [])
            }
            for post_bal in meta.get("postTokenBalances") or []:
                owner = post_bal.get("owner", "")
                if owner != address:
                    continue
                mint = post_bal.get("mint", "")
                idx = post_bal.get("accountIndex")
                post_amount = float(
                    post_bal.get("uiTokenAmount", {}).get("uiAmount") or 0
                )
                pre_amount = pre_tokens.get((idx, mint), 0)
                delta = post_amount - pre_amount
                if delta > 0:
                    # Resolve token symbol
                    token_sym = "SOL"
                    for sym, m in [("USDC", self._usdc_mint)]:
                        if mint == m:
                            token_sym = sym
                            break

                    if token_filter and token_sym.upper() != token_filter.upper():
                        continue

                    incoming.append(
                        {
                            "tx_hash": sig,
                            "from_address": "",  # SPL transfers don't easily expose sender
                            "amount": delta,
                            "token": token_sym,
                            "timestamp": block_time,
                        }
                    )

            # Check native SOL transfers
            if not token_filter or token_filter.upper() == "SOL":
                account_keys = (
                    tx.get("transaction", {}).get("message", {}).get("accountKeys", [])
                )
                pre_balances = meta.get("preBalances", [])
                post_balances = meta.get("postBalances", [])
                for i, key_info in enumerate(account_keys):
                    pubkey = (
                        key_info
                        if isinstance(key_info, str)
                        else key_info.get("pubkey", "")
                    )
                    if (
                        pubkey == address
                        and i < len(pre_balances)
                        and i < len(post_balances)
                    ):
                        delta_lamports = post_balances[i] - pre_balances[i]
                        if delta_lamports > 0:
                            incoming.append(
                                {
                                    "tx_hash": sig,
                                    "from_address": "",
                                    "amount": delta_lamports / 1_000_000_000,
                                    "token": "SOL",
                                    "timestamp": block_time,
                                }
                            )

        return incoming
