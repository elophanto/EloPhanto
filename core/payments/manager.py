"""PaymentsManager — central orchestrator for agent payments.

Manages wallet lifecycle (create, persist, reconnect), token transfers,
swaps, spending limits, and audit logging. Supports two wallet providers:
- "local" (default) — self-custody via eth-account + JSON-RPC, zero config
- "agentkit" — Coinbase CDP managed custody, gasless, DEX swaps
"""

from __future__ import annotations

import logging
import re
from typing import Any

from core.payments.audit import PaymentAuditor
from core.payments.limits import SpendingLimiter

logger = logging.getLogger(__name__)


class PaymentsError(Exception):
    """Raised for payment-related errors."""


class PaymentsManager:
    """Agent payments manager — routes to local or CDP wallet provider."""

    def __init__(self, db: Any, config: Any, vault: Any = None) -> None:
        self._db = db
        self._config = config
        self._vault = vault
        self._auditor = PaymentAuditor(db)
        self._limiter = SpendingLimiter(self._auditor, config.limits)
        self._approval_limiter = SpendingLimiter(self._auditor, config.approval)
        self._wallet_provider: Any = None
        self._wallet_address: str = ""
        self._chain: str = config.crypto.default_chain

    @property
    def wallet_address(self) -> str:
        return self._wallet_address

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def auditor(self) -> PaymentAuditor:
        return self._auditor

    @property
    def limiter(self) -> SpendingLimiter:
        return self._limiter

    async def initialize(self) -> None:
        """Initialize payments — load existing wallet or create new one."""
        if not self._config.crypto.enabled:
            logger.info("Crypto payments disabled")
            return

        if not self._vault:
            logger.warning("Vault not available — payments require vault for credentials")
            return

        # Check if we have a stored wallet address
        stored_address = self._vault.get("crypto_wallet_address")
        if stored_address:
            self._wallet_address = stored_address
            logger.info(f"Loaded wallet: {self._wallet_address} on {self._chain}")
        elif self._config.wallet.auto_create:
            await self.create_wallet()

    async def create_wallet(self) -> str:
        """Create a new agent wallet via AgentKit. Returns the address."""
        provider = await self._get_wallet_provider()
        try:
            details = provider.get_wallet_details()
            self._wallet_address = details.get("address", "")
            if not self._wallet_address:
                # Try alternate attribute access
                wallet = getattr(provider, "get_address", lambda: "")()
                self._wallet_address = str(wallet) if wallet else ""

            if self._wallet_address and self._vault:
                self._vault.set("crypto_wallet_address", self._wallet_address)

            logger.info(f"Created wallet: {self._wallet_address} on {self._chain}")
            return self._wallet_address
        except Exception as e:
            logger.error(f"Wallet creation failed: {e}")
            raise PaymentsError(f"Failed to create wallet: {e}") from e

    async def get_wallet_details(self) -> dict[str, Any]:
        """Get wallet address, chain, and balance summary."""
        result: dict[str, Any] = {
            "address": self._wallet_address,
            "chain": self._chain,
            "default_token": self._config.wallet.default_token,
        }

        if self._wallet_address and self._config.crypto.enabled:
            try:
                balance = await self.get_balance(self._config.wallet.default_token)
                result["balance"] = balance
            except Exception as e:
                result["balance_error"] = str(e)

        # Spending summary
        result["daily_spent"] = await self._auditor.get_daily_total()
        result["monthly_spent"] = await self._auditor.get_monthly_total()
        result["daily_limit"] = self._config.limits.daily
        result["monthly_limit"] = self._config.limits.monthly

        return result

    async def get_balance(self, token: str = "USDC") -> dict[str, Any]:
        """Get balance for a specific token."""
        provider = await self._get_wallet_provider()
        try:
            if token.upper() in ("ETH", "SOL", "POL"):
                balance = provider.get_balance()
                return {"token": token, "amount": str(balance), "chain": self._chain}
            else:
                # Local provider has get_erc20_balance; CDP uses get_wallet_details
                if hasattr(provider, "get_erc20_balance"):
                    balance = provider.get_erc20_balance(provider._get_token_address(token))
                    return {"token": token, "amount": str(balance), "chain": self._chain}
                else:
                    details = provider.get_wallet_details()
                    return {
                        "token": token,
                        "amount": details.get("balance", "0"),
                        "chain": self._chain,
                    }
        except Exception as e:
            raise PaymentsError(f"Failed to get balance: {e}") from e

    async def transfer(
        self,
        to: str,
        amount: float,
        token: str,
        task_context: str | None = None,
    ) -> dict[str, Any]:
        """Transfer tokens from agent wallet. Checks limits first."""
        # Validate address
        if not self.validate_address(to, self._chain):
            raise PaymentsError(f"Invalid address format: {to}")

        # Check spending limits
        check = await self._limiter.check(amount, token, to)
        if not check.allowed:
            raise PaymentsError(f"Spending limit exceeded: {check.reason}")

        # Log pending
        audit_id = await self._auditor.log(
            tool_name="crypto_transfer",
            amount=amount,
            currency=token,
            recipient=to,
            payment_type="crypto",
            provider=self._config.crypto.provider,
            chain=self._chain,
            status="pending",
            task_context=task_context,
        )

        # Execute transfer
        provider = await self._get_wallet_provider()
        try:
            if token.upper() in ("ETH", "SOL", "POL"):
                result = provider.native_transfer(to=to, amount=str(amount))
            else:
                result = provider.transfer(to=to, amount=str(amount), token=token)

            tx_hash = str(result) if result else ""
            await self._auditor.update_status(audit_id, "executed", transaction_ref=tx_hash)

            return {
                "success": True,
                "tx_hash": tx_hash,
                "amount": amount,
                "token": token,
                "to": to,
                "chain": self._chain,
            }
        except Exception as e:
            await self._auditor.update_status(audit_id, "failed", error=str(e))
            raise PaymentsError(f"Transfer failed: {e}") from e

    async def swap(
        self,
        from_token: str,
        to_token: str,
        amount: float,
        task_context: str | None = None,
    ) -> dict[str, Any]:
        """Swap tokens on DEX. Checks limits first."""
        # Check provider supports swaps
        provider = await self._get_wallet_provider()
        if hasattr(provider, "supports_swap") and not provider.supports_swap():
            raise PaymentsError(
                "Token swaps are not supported with the local wallet provider. "
                "Set provider: agentkit in config.yaml for DEX swap support."
            )

        # Check spending limits (use amount in from_token terms)
        check = await self._limiter.check(amount, from_token, f"swap:{from_token}->{to_token}")
        if not check.allowed:
            raise PaymentsError(f"Spending limit exceeded: {check.reason}")

        # Log pending
        audit_id = await self._auditor.log(
            tool_name="crypto_swap",
            amount=amount,
            currency=from_token,
            recipient=f"swap:{from_token}->{to_token}",
            payment_type="swap",
            provider=self._config.crypto.provider,
            chain=self._chain,
            status="pending",
            task_context=task_context,
        )

        # Execute swap
        try:
            # AgentKit swap via action provider
            agent_kit = self._get_agent_kit(provider)
            actions = agent_kit.get_actions()
            swap_action = None
            for action in actions:
                if "swap" in getattr(action, "name", "").lower():
                    swap_action = action
                    break

            if swap_action:
                result = swap_action.execute(
                    from_token=from_token,
                    to_token=to_token,
                    amount=str(amount),
                )
            else:
                # Fallback: direct swap call if available
                result = provider.swap(from_token=from_token, to_token=to_token, amount=str(amount))

            tx_hash = str(result) if result else ""
            await self._auditor.update_status(audit_id, "executed", transaction_ref=tx_hash)

            return {
                "success": True,
                "tx_hash": tx_hash,
                "from_token": from_token,
                "to_token": to_token,
                "amount": amount,
                "chain": self._chain,
            }
        except Exception as e:
            await self._auditor.update_status(audit_id, "failed", error=str(e))
            raise PaymentsError(f"Swap failed: {e}") from e

    async def get_swap_price(self, from_token: str, to_token: str, amount: float) -> dict[str, Any]:
        """Get a price quote for a swap without executing."""
        try:
            provider = await self._get_wallet_provider()
            if hasattr(provider, "supports_swap") and not provider.supports_swap():
                return {
                    "from_token": from_token,
                    "to_token": to_token,
                    "amount": amount,
                    "error": "Swap quotes not available with local wallet provider",
                    "chain": self._chain,
                }
            agent_kit = self._get_agent_kit(provider)
            actions = agent_kit.get_actions()
            for action in actions:
                if "price" in getattr(action, "name", "").lower():
                    result = action.execute(
                        from_token=from_token, to_token=to_token, amount=str(amount)
                    )
                    return {
                        "from_token": from_token,
                        "to_token": to_token,
                        "amount": amount,
                        "quote": str(result),
                        "chain": self._chain,
                    }
            return {
                "from_token": from_token,
                "to_token": to_token,
                "amount": amount,
                "quote": "Price quote unavailable",
                "chain": self._chain,
            }
        except Exception as e:
            return {
                "from_token": from_token,
                "to_token": to_token,
                "amount": amount,
                "error": str(e),
                "chain": self._chain,
            }

    def validate_address(self, address: str, chain: str = "base") -> bool:
        """Validate a crypto address format."""
        if chain in ("base", "ethereum", "polygon", "arbitrum"):
            return bool(re.match(r"^0x[0-9a-fA-F]{40}$", address))
        if chain == "solana":
            return bool(re.match(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$", address))
        return False

    def get_approval_tier(self, amount: float) -> str:
        """Get approval tier for an amount."""
        approval = self._config.approval
        if amount >= approval.cooldown_above:
            return "cooldown"
        if amount >= approval.confirm_above:
            return "confirm"
        if amount >= approval.always_ask_above:
            return "always_ask"
        return "standard"

    async def check_low_balance(self) -> str | None:
        """Check if wallet balance is below alert threshold. Returns message or None."""
        if not self._wallet_address or not self._config.crypto.enabled:
            return None
        try:
            balance_info = await self.get_balance(self._config.wallet.default_token)
            amount = float(balance_info.get("amount", 0))
            if amount < self._config.wallet.low_balance_alert:
                return (
                    f"Low balance: {amount} {self._config.wallet.default_token} "
                    f"remaining on {self._chain}. "
                    f"Fund {self._wallet_address} to continue payments."
                )
        except Exception:
            pass
        return None

    async def _get_wallet_provider(self) -> Any:
        """Lazy-initialize wallet provider based on config.crypto.provider."""
        if self._wallet_provider is not None:
            return self._wallet_provider

        if not self._vault:
            raise PaymentsError("Vault not available. Unlock vault to use payments.")

        provider_type = self._config.crypto.provider

        if provider_type == "local":
            self._wallet_provider = self._init_local_provider()
        elif provider_type == "agentkit":
            self._wallet_provider = self._init_cdp_provider()
        else:
            raise PaymentsError(f"Unknown crypto provider: {provider_type}")

        return self._wallet_provider

    def _init_local_provider(self) -> Any:
        """Initialize local self-custody wallet provider."""
        try:
            from core.payments.local_wallet import LocalWalletProvider

            rpc_url = getattr(self._config.crypto, "rpc_url", "") or None
            return LocalWalletProvider(
                vault=self._vault,
                chain=self._chain,
                rpc_url=rpc_url,
            )
        except ImportError:
            raise PaymentsError(
                "eth-account not installed. Run ./setup.sh to reinstall dependencies."
            )

    def _init_cdp_provider(self) -> Any:
        """Initialize Coinbase AgentKit wallet provider."""
        api_key_name = self._vault.get(self._config.crypto.cdp_api_key_name_ref)
        api_key_private = self._vault.get(self._config.crypto.cdp_api_key_private_ref)

        if not api_key_name or not api_key_private:
            raise PaymentsError(
                "CDP API credentials not found in vault. Run:\n"
                "  elophanto vault set cdp_api_key_name YOUR_KEY_NAME\n"
                "  elophanto vault set cdp_api_key_private YOUR_PRIVATE_KEY"
            )

        try:
            from coinbase_agentkit import CdpWalletProvider, CdpWalletProviderConfig

            network_id = f"{self._chain}-mainnet"
            if self._chain == "base":
                network_id = "base-mainnet"

            wallet_config = CdpWalletProviderConfig(
                api_key_name=api_key_name,
                api_key_private=api_key_private,
                network_id=network_id,
            )
            return CdpWalletProvider(wallet_config)

        except ImportError:
            raise PaymentsError(
                "coinbase-agentkit not installed. Run: uv pip install coinbase-agentkit"
            )

    def _get_agent_kit(self, provider: Any) -> Any:
        """Get or create AgentKit instance from wallet provider."""
        if hasattr(self, "_agent_kit_instance"):
            return self._agent_kit_instance

        try:
            from coinbase_agentkit import AgentKit, AgentKitConfig

            self._agent_kit_instance = AgentKit(AgentKitConfig(wallet_provider=provider))
            return self._agent_kit_instance
        except ImportError:
            raise PaymentsError("coinbase-agentkit not installed")
