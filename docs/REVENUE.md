# Revenue Operations

The reference EloPhanto instance runs a set of autonomous, real-money
economic experiments. This is the detail behind the "Revenue operations"
section of the [README](../README.md) — kept here so the README stays a
high-level intro.

> **Not financial advice, and not a promise of returns.** These are the
> agent's own autonomous experiments on the reference instance. A fresh
> install starts with none of this; you turn on what you want.

## $ELO token (Solana)

The reference instance launched its own SPL token, **$ELO**, on
[pump.fun](https://pump.fun) as a unit of account it controls — holders
get access / priority on jobs the agent can do, and payments can route
through it.

- **Contract address:** `BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump`
- **pump.fun:** https://pump.fun/coin/BwUgJBQffm4HM49W7nsMphStJm4DbA5stuo4w7iwpump

The token is *not* required to run EloPhanto — it's specific to the
reference instance's experiments.

## pump.fun livestream

The reference instance runs its own 24/7 pump.fun livestream — looped
video or TTS-narrated thoughts — and posts to the livechat, driven by
the `pump_livestream` / `pump_chat` / `pump_say` tools. End-to-end
streaming design (WHIP/RTMP via LiveKit, voice mode, on-stream captions,
ffmpeg supervisor) is documented in
[65-PUMPFUN-LIVESTREAM.md](65-PUMPFUN-LIVESTREAM.md).

## Prediction markets (Polymarket)

Places real CLOB orders on Polygon behind an owner-approval gate, with a
risk engine (edge filter + Kelly sizing + maker preference + circuit
breaker) and a calibration audit that tracks a Brier score and realized
vs claimed probability. See
[71-POLYMARKET-RISK.md](71-POLYMARKET-RISK.md) and
[72-POLYMARKET-CALIBRATION.md](72-POLYMARKET-CALIBRATION.md).

## Freelance work

Finds gigs, applies, delivers the work, and collects USDC — same agent
loop, same vault, same wallet.

## Self-custody

Every dollar lands in a wallet whose private key the agent holds in its
own encrypted vault. The owner sets daily / per-transaction /
per-merchant spending limits; anything above the limit asks first. See
[15-PAYMENTS.md](15-PAYMENTS.md) and
[51-PAYMENT-REQUESTS.md](51-PAYMENT-REQUESTS.md).

## Social posting

`twitter_post` is exercised daily by the reference instance at
[@EloPhanto](https://x.com/EloPhanto) (Unicode-safe insert, pre/post
media verification). `youtube_upload` / `tiktok_upload` ship as
scaffolding. See [56-CONTENT-MONETIZATION.md](56-CONTENT-MONETIZATION.md).
