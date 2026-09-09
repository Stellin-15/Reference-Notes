# Payments & Fintech Engineering — In-Depth Reference

The engineering discipline underneath any product that moves money —
idempotency, ledgers, and the compliance surface that makes payments
genuinely different from typical CRUD engineering.


## 1. IDEMPOTENCY — THE FOUNDATIONAL PAYMENTS PATTERN

A network timeout on a payment API call is fundamentally AMBIGUOUS — did
the charge succeed and the response got lost, or did it never happen at
all? Retrying blindly risks a DOUBLE CHARGE. The fix (see API Design
deep dive's coverage of this pattern): a client-generated
**idempotency key** sent with the request; the server stores the result
keyed by that idempotency key, and a RETRIED request with the same key
returns the ORIGINAL result instead of re-executing the charge — this
single pattern is why Stripe/every serious payments API requires an
idempotency key on any state-changing request, not an optional nicety.

```python
# Idempotent charge creation pattern
def create_charge(idempotency_key, amount, customer_id):
    existing = db.get_charge_by_idempotency_key(idempotency_key)
    if existing:
        return existing  # Already processed — return the ORIGINAL result, don't re-charge
    charge = process_payment(amount, customer_id)
    db.save_charge(idempotency_key, charge)
    return charge
```


## 2. DOUBLE-ENTRY LEDGERS

Every financial transaction affects AT LEAST two accounts, and the sum
of all debits must always equal the sum of all credits — this isn't
accounting tradition for its own sake, it's a genuinely powerful
INVARIANT that makes bugs detectable: if a system's ledger ever fails to
balance, you know immediately something is wrong, before a customer
complaint or an audit surfaces it independently.

```
Customer pays $100 for a product:
  Debit:  Customer's Cash account       -$100
  Credit: Customer's Purchases account  +$100
  (Merchant side, separately)
  Debit:  Merchant's Receivables        +$100
  Credit: Merchant's Revenue            +$100

Every entry is IMMUTABLE once written — corrections are made via a NEW
reversing entry, never by editing/deleting a past entry — this preserves
a complete, auditable history and is a real, non-negotiable requirement
in any serious ledger design (see Compliance & Governance deep dive's
audit-logging discussion for the parallel principle).
```


## 3. PAYMENT PROCESSING FLOW & PCI SCOPE (see also Compliance & Governance deep dive)

```
Customer -> [Your app] -> [Payment processor, e.g. Stripe] -> [Card network, e.g. Visa] -> [Issuing bank]
                                                             -> [Acquiring bank]
```

The standard architecture minimizing YOUR compliance burden: use a
hosted payment field/tokenization (Stripe Elements, Braintree Drop-in) so
raw card numbers go DIRECTLY from the customer's browser to the
processor, never touching your own servers — your system only ever
handles a TOKEN representing the payment method, dramatically reducing
PCI-DSS scope (see Compliance & Governance deep dive's SAQ-level discussion).

**Webhooks & eventual consistency** — payment status often changes
ASYNCHRONOUSLY (a bank transfer clears days later, a dispute is filed
weeks later) — production payment systems must handle webhook-driven
status updates arriving out of order or with delay, and MUST verify
webhook signatures (HMAC, see Cryptography deep dive) to prevent a
forged "payment succeeded" webhook from being trusted blindly.


## 4. RECONCILIATION

Comparing your OWN records against the payment processor's/bank's
records to catch discrepancies (a charge you recorded that the processor
doesn't show, or vice versa) — a genuinely essential, often-underbuilt
operational process; automated reconciliation jobs comparing daily
settlement reports against internal ledger entries are standard
production infrastructure at any real payments company, not an
afterthought bolted on after a discrepancy incident forces the issue.


## 5. NICHE BUT REAL

- **Idempotency window/expiry** — idempotency keys typically need a
  defined retention period (Stripe's is 24 hours) — a genuinely
  practical operational decision balancing storage cost against how long
  a client might reasonably retry.
- **Currency handling — never use floating point for money** — floating-
  point arithmetic's rounding errors are unacceptable for financial
  calculations; store amounts as INTEGER minor units (cents, not
  dollars) or use a dedicated decimal/fixed-point type — a real, common
  and completely avoidable bug class in fintech code written by engineers unfamiliar with this convention.
- **Chargebacks & dispute handling** — a genuinely distinct workflow
  from a normal refund (initiated by the CARD NETWORK/issuing bank, not
  the merchant, with evidence-submission deadlines and real financial
  penalties for high chargeback rates) — payment systems need explicit
  state machines modeling dispute lifecycle stages, not just "paid/refunded" binary status.
- **Idempotent webhook processing on the RECEIVING end** — payment
  processors explicitly warn that webhooks CAN be delivered more than
  once — receiving systems must be idempotent on the CONSUMING side too
  (deduplicate by webhook event ID), mirroring the same idempotency
  discipline required on the sending/charging side.
- **Strong Customer Authentication (SCA) / 3D Secure** — European
  regulation (PSD2) requiring additional authentication (often a
  redirect to the customer's bank for verification) for many online
  card payments — a real, significant flow-design constraint for any
  payments product serving European customers, adding genuine UX/
  engineering complexity beyond a simple "submit card, get charged" flow.
- **Money movement rails beyond cards**: ACH (US bank transfers, slower,
  cheaper, reversible for longer), wire transfers (fast, largely
  irreversible, used for large amounts), and real-time payment rails
  (FedNow, RTP in the US; instant payment schemes elsewhere) each have
  genuinely different settlement timing, reversibility, and failure-
  mode characteristics that shape system design decisions around when
  to consider a payment "final."
