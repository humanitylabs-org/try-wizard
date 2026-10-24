# Headless original-0.6.1 acceptance driver

This is a **test-only driver**, not a replacement production Host or a new guest
image. It never launches either App, `NSApplication`, `NSWorkspace`, Apple Events,
Screen Sharing, or an unlock/permission prompt. No preferences or TCC writes.

## Outcome / scope

Focused working slice: compile the actual production VZ/activation code into a
CLI, boot the known original disk clone normally, apply the sealed cold migration,
then verify preservation, repeat admission, and stopped rollback on a second
clone. Parent owns execution admission, independent result review, integration,
and any release. This folder changes no production implementation.

Production pin: `c7952d68e6a61da74b1e26485293cb7b5d881c7b` (build 307).
Harness commit is separate. `build_and_run.py` builds a uniquely named native
307 candidate from a separate clean checkout at that exact production pin, using
the unchanged factory and frozen runtime archives. Public 306 and earlier 307
candidates remain untouched; nothing is published.

## Run

Stage a clean Git checkout of the pushed harness commit on ThalesMedia. The spec
uses explicit `sourceDir`, `harnessSource`, `evidenceRoot` (must not exist),
`baselineDisk`, `bootDir`, `candidateApp`, and `oldApp` paths. `bootDir`'s sibling
`manifest.json` is copied unchanged, not manufactured as an installed receipt.

Submit **through `wizard_heavy_submit` only**:

```
<Thales Python> <sourceDir>/next/mac/Tests/HeadlessCold/run.py \
  --spec <immutable spec.json> --worker-lease inherited
```

No child submission, nested lock, direct SSH compile, detached workload, SDK
installation, or fixture substituted for VM acceptance. A failed run retains its
private evidence and clones. Use a new evidenceRoot only after the parent has
read the previous failure; never replay a partially migrated disk as an original.
The parent-ready payload is prepared separately because child heavy admissions
are unavailable. The Python runner is executable and controls its child directly.

For a new native307 candidate plus this acceptance, submit `build_and_run.py`
instead of `run.py`, with the same `--spec` / `--worker-lease inherited` arguments.
Additional spec keys: `productionDir`, `productionSource` (exact pin above),
`python`, `uv`, `frozenPayload`, `publicApp`, and `sparkle`. Both Git checkouts
must be clean, the candidate path must not exist, and evidence is write-once.
The wrapper preserves the existing build/signing/feed/payload recipe and runs
no GUI legacy probe. It records phase logs, source hashes and frozen archive
hashes, then creates a separate headless spec/report beneath its evidence root.
Neither a build nor helper fixtures establish migration acceptance.

Cheap local contracts (not VM evidence):

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s next/mac/Tests/HeadlessCold -p 'test_*.py' -v
```

## Exact production reuse

`build_driver.py` refuses drift against the production Git pin before extracting:

* Host `VMController`, `Pipe2`, and loopback health bridges: production `.cached`
  + `.full` disk attachment, cold PID1 kernel commandline, serial command, readonly
  sealed payload, vsock patch command, graceful stop, and status writes.
* Entire `WizardGuestActivation`, `UpdateContract`, `DiskIdentity`, and
  `GuestPatchCommand` implementations, unchanged (activation's unused AppKit import
  becomes Foundation; this adapter is recorded separately).
* The actual stopped admission block from `WizardUpdater`: boot hashes, release
  validation, ownership/lease locks, APFS snapshot, cold transaction creation.
* Exact `cold-config.py` and `stack-preservation.py` in the private guest auditor;
  migration itself uses only the sealed installed payload.

Every source hash, extracted line range, adapter replacement, and generated Swift
hash is recorded in `build/provenance.json`. Source checks run before compilation.
The only production-source adapters are replacing the now-unused AppKit import
with Foundation, explicit data-root input, refusal of guest open-URL requests, and
supplying the sealed installed bundle instead of CLI bundle
to stopped admission. `HostControl` replaces notification/AppKit launch transport
with direct VZ calls; it does not implement migration, snapshot or rollback.
The CLI signs with only Apple's virtualization entitlement.

## Real gates and evidence

`report.json` is checkpointed after each gate. `success` remains false until all
phases and cleanup checks pass. Failure exits nonzero and retains diagnostics.

1. Normal boot of an APFS clone. Require actual stock image, exact original Docker
   versions, existing chats, and no migration/policy/maintenance state. No manual
   transaction or API priming. This is original guest runtime evidence, **not** an
   old App UI test. Original app version and byte inventory are independently read.
2. Cold production activation. Capture pre/post private-vsock audit and production
   guest receipt. Verify no stock engine running, unsaturated Docker event history
   since cold boot, production live-denial probes including post-commit, normal
   health and maintenance release. Before shutdown, replace dockerd in the SAME
   cold boot with `SendSIGKILL=no`; require a changed daemon PID, unchanged boot ID,
   persisted AuthZ config, disabled retained restart policies, unchanged stock
   StartedAt values, and rejected stock create/start/restart/unpause/exec routes.
   Keep unsaturated event-ring evidence on both sides of replacement (not a
   continuous kernel trace). The next normal boot must restore the exact original
   daemon bytes and retained policies through the production offline prestart gate.
   Preserve serial logs before normal boot truncates the production console path.
   The wrapper also runs seven lightweight Swift scenarios through actual Host
   stop/prepareUpdate and activation implementations (fake VZ I/O, accelerated
   timeout, fixture bundle path). Cold and modern timeouts and apply failures must
   retain the backup, refuse activation, never force, and ignore late stopped
   callbacks; concurrent stop is failure and clean stop still succeeds.
3. Preservation: production auth/env/model/token guard; compare field-hashed auth,
   exact config bytes after the proven product-plugin append/serialization followed
   by the production SSH scalar migration (no ignored owner keys), existing session
   and message rows in every discovered SQLite DB, owner content trees (memories,
   skills, documents, sessions, Runtipi media, Files, managed SSH key), SOUL/USER/
   AGENTS files, account-app data and installed app-data directory identities.
   Non-chat runtime-table hashes are retained but not asserted unchanged; startup
   heartbeat/FTS/cache churn is not chat loss. Unenumerated custom app state is not
   claimed as exhaustively inspected. The stopped rollback byte proof covers the
   entire selected disk. No model request, credential bytes or chat text is logged.
4. Repeat normal launch must leave completion, transaction, and guest receipt bytes
   unchanged; production `legacyBootstrapNeeded` must be false.
5. On a separate clone of the same observed stopped original, run the real patch
   again, then inject a **host response failure only after the real successful apply
   receipt and post-apply audit**. Never alter the public or private guest payload.
   Production activation performs the stopped APFS restore. Compare every restored
   disk byte with its rollback snapshot **before** old normal boot; then compare old
   runtime, chats, auth, config, apps and owner content semantically.
6. Replace that disposable stopped disk with an identical-byte different-inode
   clone. Production interrupted recovery must reject the changed identity without
   changing current disk, backup, or transaction journal.
7. The upgraded guest acquires a real `ManagedMaintenance.enter()` operation
   reservation, requires production acquire to refuse `runtime_operation_in_flight`,
   and closes only its own reservation. This is an actual owned-operation exclusion
   proof, **not** a model-generation or active-chat cancellation test.
8. Confirm graceful VZ stop and no open image descriptors; no owner-lock release
   before descriptor closure. Production stop retains VZ in its 90-second timeout
   closure, so the adapter waits for actual `lsof` closure before returning stopped.
   No forced stop counts as success. Read back preferences unchanged, baseline and
   installed apps byte-identical, disjoint foreign process identity/listeners
   unchanged, and console still locked. CLI health bridges are loopback only;
   root shell exists solely on this owned VM's private vsock, never TCP.

## Config expectation evidence

The failed predecessor harness predicted only `terminal.ssh_key`. A read-only
`debugfs` examination of its cleanly stopped, task-owned upgraded ext4 disk found
the updater's retained backup matched the original captured raw SHA-256 exactly.
The product-plugin backup matched the same original. The stopped final config
matched all post-apply snapshot hashes. Its only semantic changes were appending
`wizard-product` to `plugins.enabled` and moving the managed SSH key path.

Replaying the pinned `wizard-product-configure` conditional `safe_dump` followed
by `cold-config.migrate` reproduced the final config bytes exactly. Frozen WAM's
`maintenance_refresh` changes packaging only; no other config addition is waived.
`config_expectation.py` models that exact order, including no serialization when
the plugin is already enabled. Unknown/provider/model/owner keys remain protected;
repeat requires exact bytes and rollback requires the captured original bytes.
The guest hashes a single raw-byte read. Tests execute the actual product config
block on synthetic fixtures, and adversarial mutations still fail `run.compare`.
The wrapper pins the product writer and checks the frozen payload's writer bytes
against production. Private values are not committed, printed, or copied out.
This correction is QA-only; production remains the reviewed `c7952d6` ancestor
symlink fix. The old failed receipt stays failed; a new full run is still required.

## Evidence boundaries

* Passing Python contracts establish extraction/comparison behavior, not compilation,
  VM boot, migration, native consent, installed App launch, or final release success.
* Adapter-selected consent is test authorization, never a claimed physical click.
* Authenticated producer/bundle hashes and guest receipts remain production checks;
  GUI notification peer-envelope wiring is outside this headless adapter layer.
* Docker event evidence is bounded to recorded `since`/`until`; a saturated 256-event
  buffer fails closed. Post-commit production denial plus unchanged fence source
  covers the transition to stopped; no claim of a kernel-level continuous trace.
* No source-only or fixture verdict may set the real-VM report to success. Parent
  must inspect the actual durable command result and exact report before acceptance.
