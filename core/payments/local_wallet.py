"""LocalWalletProvider — self-custody wallet using eth-account + JSON-RPC.

Stores the private key encrypted in the EloPhanto vault.
Supports native ETH transfers and ERC-20 token transfers on Base.
Does NOT support swaps (requires CDP/AgentKit provider).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Well-known chain configuration
_CHAIN_CONFIG: dict[str, dict[str, Any]] = {
    "base": {
        "chain_id": 8453,
        "rpc_url": "https://mainnet.base.org",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "base-sepolia": {
        "chain_id": 84532,
        "rpc_url": "https://sepolia.base.org",
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    },
    "ethereum": {
        "chain_id": 1,
        "rpc_url": "https://eth.llamarpc.com",
        "usdc": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
}

# Token decimals
_TOKEN_DECIMALS: dict[str, int] = {
    "usdc": 6,
    "usdt": 6,
    "dai": 18,
    "eth": 18,
}


class LocalWalletProvider:
    """Local self-custody wallet — zero config, auto-creates.

    Uses eth-account for key generation/signing and raw JSON-RPC
    calls via urllib for on-chain operations. No external API keys needed.
    """

    def __init__(self, vault: Any, chain: str = "base", rpc_url: str | None = None) -> None:
        self._vault = vault
        self._chain = chain
        self._account: Any = None

        chain_cfg = _CHAIN_CONFIG.get(chain, _CHAIN_CONFIG["base"])
        self._chain_id: int = chain_cfg["chain_id"]
        self._rpc_url: str = rpc_url or chain_cfg["rpc_url"]
        self._usdc_address: str = chain_cfg.get("usdc", "")

        self._load_or_create_account()

    # ------------------------------------------------------------------
    # Account lifecycle
    # ------------------------------------------------------------------

    def _load_or_create_account(self) -> None:
        """Load existing key from vault or generate a new one."""
        from eth_account import Account

        stored_key = self._vault.get("local_wallet_private_key")
        if stored_key:
            self._account = Account.from_key(stored_key)
            logger.info(f"Loaded local wallet: {self._account.address}")
        else:
            self._account = Account.create()
            self._vault.set("local_wallet_private_key", self._account.key.hex())
            self._vault.set("crypto_wallet_address", self._account.address)
            logger.info(f"Created local wallet: {self._account.address}")

    # ------------------------------------------------------------------
    # Public interface (matches CDP provider pattern)
    # ------------------------------------------------------------------

    def get_wallet_details(self) -> dict[str, Any]:
        """Return wallet address and chain info."""
        return {
            "address": self._account.address,
            "chain": self._chain,
            "provider": "local",
        }

    def get_address(self) -> str:
        """Return the wallet address."""
        return self._account.address

    def get_balance(self) -> str:
        """Get native ETH balance as a decimal string."""
        result = self._rpc_call("eth_getBalance", [self._account.address, "latest"])
        wei = int(result, 16)
        return str(wei / 10**18)

    def get_erc20_balance(self, token_address: str) -> str:
        """Get ERC-20 token balance for this wallet."""
        # balanceOf(address) selector = 0x70a08231
        data = "0x70a08231" + self._encode_address(self._account.address)
        result = self._rpc_call("eth_call", [{"to": token_address, "data": data}, "latest"])
        raw = int(result, 16) if result and result != "0x" else 0
        # Detect decimals from known tokens
        decimals = self._get_token_decimals_by_address(token_address)
        return str(raw / 10**decimals)

    def native_transfer(self, to: str, amount: str) -> str:
        """Send native ETH. Returns transaction hash."""
        from eth_account import Account
        from eth_utils import to_checksum_address

        to = to_checksum_address(to)
        wei_amount = int(float(amount) * 10**18)
        nonce = int(
            self._rpc_call("eth_getTransactionCount", [self._account.address, "pending"]),
            16,
        )
        gas_price = int(self._rpc_call("eth_gasPrice", []), 16)

        tx = {
            "to": to,
            "value": wei_amount,
            "gas": 21000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": self._chain_id,
        }

        signed = Account.sign_transaction(tx, self._account.key)
        raw_tx = "0x" + signed.raw_transaction.hex()
        tx_hash = self._rpc_call("eth_sendRawTransaction", [raw_tx])
        logger.info(f"Native transfer sent: {tx_hash}")
        return tx_hash

    def transfer(self, to: str, amount: str, token: str = "USDC") -> str:
        """Send ERC-20 tokens. Returns transaction hash."""
        from eth_account import Account
        from eth_utils import to_checksum_address

        token_address = to_checksum_address(self._get_token_address(token))
        to = to_checksum_address(to)
        decimals = self._get_token_decimals(token)
        token_amount = int(float(amount) * 10**decimals)

        # Encode transfer(address, uint256) calldata
        calldata = "0xa9059cbb" + self._encode_address(to) + self._encode_uint256(token_amount)

        nonce = int(
            self._rpc_call("eth_getTransactionCount", [self._account.address, "pending"]),
            16,
        )
        gas_price = int(self._rpc_call("eth_gasPrice", []), 16)

        # Estimate gas
        estimate_tx = {
            "from": self._account.address,
            "to": token_address,
            "data": calldata,
        }
        gas_estimate = int(self._rpc_call("eth_estimateGas", [estimate_tx]), 16)
        gas_limit = int(gas_estimate * 1.2)  # 20% buffer

        tx = {
            "to": token_address,
            "data": calldata,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": self._chain_id,
            "value": 0,
        }

        signed = Account.sign_transaction(tx, self._account.key)
        raw_tx = "0x" + signed.raw_transaction.hex()
        tx_hash = self._rpc_call("eth_sendRawTransaction", [raw_tx])
        logger.info(f"ERC-20 transfer sent: {tx_hash}")
        return tx_hash

    def supports_swap(self) -> bool:
        """Local wallet does not support DEX swaps."""
        return False

    # ------------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------------

    def _rpc_call(self, method: str, params: list[Any]) -> Any:
        """Make a JSON-RPC call to the configured RPC endpoint."""
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
            raise RuntimeError(f"RPC error: {msg}")
        return data.get("result")

    # ------------------------------------------------------------------
    # ABI encoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_address(address: str) -> str:
        """Zero-pad address to 32 bytes for ABI encoding."""
        return address.lower().replace("0x", "").zfill(64)

    @staticmethod
    def _encode_uint256(value: int) -> str:
        """Encode uint256 as 32-byte hex string."""
        return hex(value)[2:].zfill(64)

    def _get_token_address(self, symbol: str) -> str:
        """Resolve token symbol to contract address on current chain."""
        tokens: dict[str, str] = {"usdc": self._usdc_address}
        addr = tokens.get(symbol.lower())
        if not addr:
            raise ValueError(
                f"Unknown token: {symbol}. "
                f"Local wallet supports: {', '.join(t.upper() for t in tokens if tokens[t])}"
            )
        return addr

    @staticmethod
    def _get_token_decimals(symbol: str) -> int:
        """Get decimal places for a token symbol."""
        return _TOKEN_DECIMALS.get(symbol.lower(), 18)

    def _get_token_decimals_by_address(self, address: str) -> int:
        """Get decimals for a known token address."""
        addr_lower = address.lower()
        if addr_lower == self._usdc_address.lower():
            return 6
        return 18
