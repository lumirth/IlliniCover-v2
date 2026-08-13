# RevenueCat reconciliation

RevenueCat is the billing authority; IlliniCover stores idempotent webhook and
reconciliation receipts. Development and preview use Test Store values and
must never receive production server secrets. TestFlight uses Apple sandbox and
must produce a no-charge receipt before beta.

When webhook delivery fails, first repair or rotate the webhook credential,
then replay provider events where RevenueCat supports it. Run the bounded
management command from the current immutable backend image through the normal
pooled jobs identity:

```bash
python server/manage.py reconcile_revenuecat --settings=config.settings.production
```

In production, execute this command as an explicit Cloud Run Job, not on a
developer laptop with copied secrets. Confirm its JobRun receipt includes the
code revision and success summary, compare affected account entitlement state
to RevenueCat customer state, and verify duplicate delivery remains
idempotent. Never edit entitlement rows to manufacture success. Escalate any
unexplained paid entitlement or charge to RevenueCat/Apple records before
changing application state.
