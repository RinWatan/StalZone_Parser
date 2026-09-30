# Auction scan optimization

Base: latest colleague commit 9a1ec36, isolated branch codex/auction-performance.
Preserve overlay mode restoration, game search and client PDA maps.
Keep official EXBO prices/catalog and the same pagination, quality grouping,
commission, liquidity criteria and budget rules. Never include exbo.json in Git/EXE.

Measured baseline on 26 identical catalogue targets: current 54 requests / 21.846s,
old f40ad33 43 requests / 17.794s. Eleven extra calls check history for empty
lot lists, which cannot yield a deal. Request average latency is ~1.5s; four
workers do not saturate the existing paced pool. Transport resets close a
shared client on any HTTP error, risking other workers' requests.

- [x] Regression tests: no history for empty/nonbuyable lots, intact profitable
  deal calculations, selective retry/pool reuse, cancellation of queued work.
- [x] Restore old empty-lot short circuit, preserve global rate pacing, increase
  scan concurrency within existing connection capacity. Cancel pending work on stop.
- [x] Retry transient transport/server/rate failures only; do not close a shared
  client while other requests run. Compare real identical-sample timing and requests.
- [x] Verify all tests, review, package latest colleague features with optimization,
  scan for credentials and publish verified branch/main using the agreed workflow.

Existing unavailable-item cache remains readable until expiry. Empty live lots
alone are not grounds to exclude an item for fourteen days: it may trade later.
The initial official database archive stays cached; it is separate from live
request time. Full scan still covers every eligible catalogue item.

Optimized actual sample: 43 requests / 11.188s (1.95x baseline). All calls
returned 200. The same snapshot eligibility/history depth is retained;
32 tests pass, including synthetic profitable deal, permanent/transient errors,
bounded stop and interruptible Retry-After waits. Retry-After interruption was
added after review. Full catalogue duration was not extrapolated as a guarantee.
Latest WebView2 integration check passed, including restored full mode, map
instance/zoom, map request ordering and temporary personal marker. The EXE
STALZONE-auction-fast.exe was built with pywebview and lz4. A running user copy
owns the global hotkey, so no second packaged copy was launched; it was left
running. Packaging and source native UI were checked independently.
