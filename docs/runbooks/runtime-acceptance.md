# Real-backend runtime acceptance

A build proves compilation, not product behavior. Acceptance installs the
normal app, talks to real Django/PostgreSQL, observes settled UI and
accessibility, and retains bounded logs and result bundles outside Git.

The detailed scenario contract is
[`ios/docs/acceptance/README.md`](../../ios/docs/acceptance/README.md). A failed
or unrun scenario remains explicit; fixture data, fake clients, SwiftUI
previews, source inspection, and old screenshots cannot substitute for it.

## Local full-system lane

From the repository root:

```bash
mise run setup
mise run up
```

Keep Django running. In another terminal, select and boot a dedicated
Simulator, then run all three checked-in plans:

```bash
export ILLINICOVER_SIMULATOR_UDID=<dedicated-simulator-udid>
mise run ios:boot
ILLINICOVER_TEST_PLAN=Fast mise run ios:test
ILLINICOVER_TEST_PLAN=UI mise run ios:test
ILLINICOVER_TEST_PLAN=Integration mise run ios:test
```

`Integration` runs `testLiveBackendShowsCoverAndDeals` through the Local app's
loopback `/api/` client. Test results are written to ignored
`.artifacts/ios/*.xcresult`. A release build supplies the RevenueCat public
Apple key to the production scheme:

```bash
ILLINICOVER_IOS_SCHEME=IlliniCover \
ILLINICOVER_REVENUECAT_APPLE_KEY=<public-sdk-key> \
mise run ios:build
```

## Manual scenarios and evidence

Use the installed app, not a preview. Exercise the scenario table against the
same backend revision under acceptance, including offline/retry behavior by
interrupting the real network boundary. Purchase, location, notification, and
accessibility states must come from their system/provider surfaces.

Capture settled frames with:

```bash
mise run ios:screenshot -- <scenario-name>
xcrun simctl spawn "$ILLINICOVER_SIMULATOR_UDID" log show \
  --last 10m --style compact --predicate 'process == "IlliniCover"'
```

Keep server logs bounded to the exercised interval and exclude credentials,
tokens, private location, message bodies, and raw user data. For each release
candidate, upload one CI/release artifact named by Git commit containing:

- app bundle/build identity, backend Git SHA, Xcode/iOS versions, device model,
  and Simulator UDID;
- `.xcresult` bundles for Fast, UI, and Integration;
- representative settled screenshots and accessibility trees in light/dark
  appearance and large Dynamic Type;
- bounded client/server logs for the captured interactions; and
- a short scenario manifest marking each row pass, fail, or not run.

Do not commit that artifact or add checksum/receipt ledgers. Accept the runtime
only when the installed identity matches the candidate, health and `/api/status`
pass, core cover/deal/identity/privacy flows work against the real backend, the
offline outbox retries without invented success, and the retained logs contain
no unexpected error or private-data disclosure.
