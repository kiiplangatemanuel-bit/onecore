# Subscription, Billing and Licensing Engine

Master specification category: **28**

## Implemented foundation
The platform now has a persistent plan catalogue, organization subscriptions with immutable price snapshots, idempotent payment-reference submission, administrator verification/rejection, renewal term extension, cancellation and audit history. Plan entitlements are stored as structured data.

## Remaining scope
Recurring automatic charging is disabled until a payment-provider mandate is configured. M-Pesa STK push/card checkout, automated dunning, tax invoices/receipts, refunds, proration, usage metering, infrastructure/AI cost attribution and centralized entitlement enforcement are not yet complete. Do not treat a submitted payment reference as settled; a platform administrator must verify it against the provider/bank statement.

See `onecore-ecosystem/docs/PLATFORM_COMMERCE_AND_ADMIN.md`.
