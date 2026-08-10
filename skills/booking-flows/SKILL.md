---
description: Book, reschedule, and cancel appointments (gym classes, restaurants, services) via API or browser
triggers:
  - book a class
  - book a session
  - reserve a slot
  - cancel my booking
  - reschedule
  - gym booking
  - make a reservation
---

## Description

Book, reschedule, and cancel appointments (gym classes, restaurants, services) via API or browser.

## Triggers

- book a class / session / court / table
- reserve a slot, make a reservation
- cancel or reschedule my booking

## Instructions

Two routes. Try them in this order — the API route is faster, more reliable, and leaves a clean
record; the browser is the fallback for consumer services with no public API.

### Route A — the service has an API

1. Confirm the credential resolves with a cheap read (`GET /me`, `/profile`, `/account`).
2. **List before you write.** Fetch the available slots and show the operator what you found,
   with times in *their* timezone. Never infer which class they meant from a partial match —
   "the 6pm spin" is ambiguous when there are two.
3. Book with `POST`, then **re-read** to confirm the booking exists. A `200` is not proof; a
   subsequent `GET` that lists the booking is.
4. Report back the confirmation id, the exact time, and the cancellation deadline if the API
   exposes one.

```
http_request(
  method="POST", url="https://api.mygym.example/v1/bookings",
  credential="gym", json={"classId": "sp-2214", "spot": 7},
  reason="Book Tuesday 18:00 spin class as the operator asked"
)
```

### Route B — browser only

Use the browser tools against the operator's logged-in profile. Log in once by hand; the session
persists. Snapshot the page, act on refs, re-snapshot between steps. Report a 2FA or captcha wall
as a blocker rather than trying to defeat it.

### Cancelling — the part that goes wrong

Cancelling is destructive and often has a fee window. Before cancelling:

- Confirm you have the **right** booking (id, date, and time all matched, not just the date).
- Say the cancellation deadline and any fee out loud before acting.
- Cancel only the operator's **own** booking. If a request would cancel, remove, or modify
  someone else's reservation, membership, or account, refuse and say why. The scope guard will
  also refuse it, but you should not have proposed it. Being able to reach an endpoint is not
  the same as being entitled to change what is behind it — that entitlement comes from the
  operator owning the account, and nothing else.

### Timezones

Book in the venue's local time, confirm in the operator's. State both when they differ. Most
booking mistakes are timezone mistakes.

## Verify

- The slot was confirmed by a follow-up read, not just a 2xx
- The confirmation id and exact local time were reported
- Cancellations named the deadline/fee before acting
- No action touched a booking or account that was not the operator's
