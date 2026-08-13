# iOS simulator acceptance artifacts

The required state-by-state runtime gate is
[`VISUAL_STATE_MATRIX.md`](VISUAL_STATE_MATRIX.md). It intentionally rejects
preview-only captures and mismatched or obstructed v1/v2 comparisons.
Normal API fixtures and bounded transport controls are documented in
[`../../../docs/runbooks/visual-acceptance.md`](../../../docs/runbooks/visual-acceptance.md).

This directory contains settled runtime evidence from the clean-room v2 app
and the read-only v1 behavioral reference. See `RUNTIME_COMPARISON.md` for the
exact toolchain, device, interactions, results, and known limitations.
