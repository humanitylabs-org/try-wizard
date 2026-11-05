# Local startup launch diagnostics

## Released 0.7.2/309 behavior

The frozen release `3756c10a65dee6195d9eb206a5e896086e891cf8` calls
`HostControl.ensureRunning()`, broadcasts `start`, then waits up to 120 seconds
for both loopback health endpoints. Its Workspace error callback only calls
`NSLog`. A foreign same-ID Host makes ensureRunning return without launching,
but the caller still broadcasts start and polls global ports. Neither case
produces a Host status error in the App's selected DataHome.

This is a launch-error handling defect, independently of any particular user's
cause. The generic timeout does not prove a VM failed. Absence of host.log and
console.log in the App's Show Logs folder points earlier than ordinary logged
VM startup, or to a different Host DataHome; it does not prove which.

## Scoped change

- Return launch/preflight errors to the selected local connection immediately.
- Check the Workspace-returned bundle URL before accepting the launch.
- Only broadcast start and start readiness probes after a successful launch
  result; abandon stale backend/generation callbacks.
- Bound Workspace completion and remaining readiness to the existing two-minute
  budget. Deliver completion once, ignoring later Workspace callbacks.
- Append selected DataHome/embedded-Host path, reuse and outcome to
  `logs/app-startup.log` even when Host never initializes. Do not overwrite or
  impersonate `host-status.json`.
- Remove the redundant installer-completion start broadcast.

This does **not** authenticate the health endpoint, verify the executable version
or DataHome of an already-running Host at the same bundle path, change the
Host/VM, reset preferences, kill another process, rebuild a guest, publish an
update, or establish the historical cause of an owner's failure. Other native
menu/updater command paths retain their existing behavior.

## Checks and evidence boundaries

`python3 next/mac/Tests/test_host_launch_errors.py` is a source-wiring guard. It
fails against the unpatched 36e46b3 baseline and passes with this change. It does
not compile Swift or execute AppKit.

`python3 next/mac/Tests/run_host_launch_checks.py` extracts the actual production
HostControl and connectLocal into a Swift fixture with fake Workspace, process
inventory, notifications, health probes, overlays and load callbacks. It writes
only its temporary directory. Run it only through the admitted macOS native job.
`--emit-only <scratch-file>` can check extraction without compiling/executing.

The fixture covers Workspace error, foreign runner, maintenance, wrong/nil
returned app, successful launch arguments/main completion, existing and newly
launched expected Host, and stale generation/backend callbacks. It launches no
actual App or Host, opens no network port and boots no VM. A passing fixture is
not real GUI/VM acceptance. Compile the actual App/Host with build.sh separately;
retain native build/fixture logs and do not claim either check before execution.
