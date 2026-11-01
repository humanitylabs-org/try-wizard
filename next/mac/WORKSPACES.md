# Native multi-Wizard workspaces (candidate)

The native registry owns the list; the page asks through the existing
`wizardNative` bridge. This implements the shared v1 switcher contract without
changing its payloads. No guest image, web switcher UI, management plane, release,
signing or notarisation is included.

## Implementation map

- **EXTEND** the existing Backend/UserDefaults store in `Shared/WorkspaceStore.swift`.
  The `backends` Data array, `activeBackend` index and `thisMac`/`remote` enum
  spellings remain compatible with 0.7.0. Reading old entries adds stable IDs
  once; names, URLs, order and selection survive. Optional subtitle and
  company/managed kinds are display-only. `thisMac` becomes `this-mac` only in
  bridge snapshots.
- **EXTEND** the existing native bridge with `workspaces.list/switch/add/rename/remove`.
  Only trusted main-frame Wizard documents can call. Other native methods remain
  active-view-only. Replies to a workspace switch are delivered to the originating
  trusted page even after it is hidden. Errors use the existing `{ok:false,error}`
  convention. Removing an entry never deletes files, stops a VM or calls a server;
  the final entry cannot be removed.
- **NEW** `App/WorkspacePages.swift` retains a lazily created WKWebView per saved
  Wizard. At most four background pages plus the active page remain. Least-recently
  used remote pages are evicted beyond that bound; returning to an evicted page
  reloads it, so its unsaved draft is not promised. The local page stays pinned so
  hidden local capture state remains available to the updater's fail-closed guard.
- **REUSE** the existing menu, add flows, dictation/orb/keyboard event routes and
  local Host health. Menu and bridge switch the same model. Cached switches swap
  native visibility/focus without navigation. Asynchronous navigation/orb fallbacks
  and keybinding/search responses cannot spill into a different selected Wizard.
- **EXTEND** document-start injection: `wizardUX.native.workspaces` merges through
  later `wizardUX` assignment and `wizardNativeCaps.workspaces` is also provided.
  Registry/status events reach every trusted loaded page, including hidden pages.
- **EXTEND** remote reachability with HEAD requests (5 s timeout), 30 s healthy
  interval and exponential failure backoff capped at 300 s. A 401/403 still means
  reachable, not authenticated. Local statuses come from existing Host health.
  No remote is stopped or administered.
- **EXTEND** restart admission to every retained local-VM page, not remote work.
  Existing native capture, Host lease and guest busy checks remain in place.

## Acceptance and isolation

**Mac compilation and UI acceptance have not been executed.** Thales was offline
and SSH timed out during banner exchange when this candidate was prepared. Keep
the PR draft until the following native checks pass. Linux source/JS tests are
supporting evidence only, not substitutes for Swift execution or native UI proof.

On Thales, stage the exact pushed revision under the external work root. Check
free space and `bash ~/wd-heal.sh`, then use the shared durable worker lock/lane.
First run existing tests on a detached worktree at this feature's base, preserving
its log, and then on the candidate:

```sh
swift test --package-path next/mac --disable-sandbox
```

The candidate adds 14 XCTest methods in `Tests/Workspaces/WorkspaceTests.swift`
(registry operations, last-entry refusal, migration/old decoder compatibility,
kind/subtitle round-trip, LRU policy and probe backoff). Compare actual existing
suite counts before/after; method counts are not execution receipts.

Build an **unsigned app-only QA bundle** against verified Sparkle 2.10.0:

```sh
SPARKLE_DIR="$VERIFIED_SPARKLE_DIR" bash next/mac/tools/build-workspaces-qa.sh "$NEW_QA_BUILD"
python3 next/mac/qa-workspaces.py \
  --app "$NEW_QA_BUILD/Wizard Switcher QA.app" --out "$NEW_QA_EVIDENCE"
```

The build prints its exact `xcrun swiftc -O -target arm64-apple-macos14.0
-swift-version 5 ...` invocation. The production build also includes both new
Swift sources. The QA build has no Host, VM or release manifest; updater failure
is expected and its notice is dismissed through the existing QA command.

The runner refuses production bundle IDs, pre-existing scratch defaults and any
other running Wizard app. Its unique bundle identity is
`org.humanitylabs.wizard.switcherqa.<uuid>`; only that defaults domain is written
with `QAHooks=true`. DataHome is task-owned and the shared path resolver honors it
only under QAHooks. Caps Lock remapping is disabled. Two Node servers bind random
loopback ports and serve only fake Wizard pages. No owner backends or VM image
are opened. This is an explicit direct-executable app-only fixture, **not**
Finder/LaunchServices, installed Host, removable-volume consent or physical-mic
acceptance. All owned processes are stopped and scratch defaults are removed;
forced cleanup makes the receipt fail.

The native runner tests migration/list/active ID, capability merge, switch bridge
reply to the hidden caller, active-only orb/dictation events, view visibility,
measured cached native view swap under 200 ms, counter/text/load-token retention,
events to hidden pages, rename across relaunch, removal and last-entry refusal.
It retains `receipt.json`, server/native logs and three WK snapshots. The timing
measures native show/layout, not photons on the display. **Open and inspect every
snapshot** before accepting the run. These fake pages are not Wizard-skin proof.

Fast supporting checks (Linux or Mac):

```sh
python3 -m unittest discover -s next/mac/Tests -p test_workspaces_source.py -v
python3 next/mac/Tests/test_window_titlebar.py
bash -n next/mac/tools/build-workspaces-qa.sh next/mac/build.sh
node --check next/mac/Tests/Workspaces/fixture.cjs
git diff --check
```

The shared CONTRACT.md is unchanged. Native QA remains the merge gate; this
candidate neither publishes an app nor alters a release/update feed.
