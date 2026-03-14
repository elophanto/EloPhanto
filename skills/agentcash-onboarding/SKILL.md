# AgentCash Onboarding

## Description
Set up AgentCash for pay-per-call access to premium APIs via x402 micropayments. Creates a wallet, optionally redeems invite credits, and installs the core AgentCash skill.

## Triggers
- agentcash
- agent cash
- set up agentcash
- onboard agentcash
- install agentcash
- agentcash wallet
- invite code agentcash
- x402
- pay per call
- micropayments api

## Instructions

AgentCash gives EloPhanto pay-per-call access to premium APIs via x402 micropayments. This is a one-time setup: wallet creation, optional invite credits, and core skill integration.

### Onboarding Flow

When the user wants to set up AgentCash:

1. **Run onboard**

   If the user has an invite code:
   ```bash
   npx agentcash@latest onboard <invite-code>
   ```

   Without an invite code:
   ```bash
   npx agentcash@latest onboard
   ```

   This creates a wallet and installs the core AgentCash skill. Without a code the user is prompted with a link to deposit or redeem credits later.

2. **Check balance**
   ```bash
   npx agentcash wallet info
   ```
   Shows wallet address, USDC balance, and deposit link. If balance is 0, direct the user to https://agentcash.dev/onboard to get free credits.

3. **Redeem a code later** (if they skipped it during onboard)
   ```bash
   npx agentcash wallet redeem <invite-code>
   ```

### After Onboarding

Once setup is complete the core AgentCash skill (installed by the onboard command) handles:
- Discovering paid endpoints: `npx agentcash discover <origin>`
- Making paid API requests: `npx agentcash fetch <url>`
- Wallet management: balance, redeem, deposit

Deposits accepted as USDC on Base or Solana.

## Resources
- Homepage: https://agentcash.dev
- Onboard / get credits: https://agentcash.dev/onboard
