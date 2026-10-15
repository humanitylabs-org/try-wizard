# Installed Host / combined-update acceptance

## Launch context matters

For the installed-path acceptance test, install the selected ad-hoc or signed
`Wizard.app` in `/Applications` (or the GUI user's `Applications`), but keep the
QA DataHome, disk, logs, evidence, source and build products on the external work
volume. Do not run `Contents/MacOS/Wizard` through SSH `Popen` and call that a
Finder/LaunchServices launch. The embedded Host and Sparkle relaunch have their
own LaunchServices lifecycle and privacy attribution. An internal DataHome can
hide this difference; it is not an external-storage fix.

`tools/native_qa_launch.py` verifies the installed MVP identity/signature and
current console owner, then uses noninteractive sudo to enter the GUI audit
session with `launchctl asuser <uid>`, drops back to that UID, and invokes
`open -g -j <app>`. Plain non-root `launchctl asuser` from SSH can fail with
`Could not switch to audit session: Operation not permitted`; the same UID is
not proof of the same audit session. Both privilege steps use `sudo -n` and
fail closed rather than prompting or broadening permissions.
It neither raises the window nor resets/grants privacy permissions. A successful
`open` is admission only. If macOS requires consent, record the exact prompt and
stop at the owner gate; never grant broad Full Disk Access just to make QA pass.

Under the existing shared **POSIX** `worker.lock` (`lockf -k`, bounded admission
and lease), run:

```
python3 tools/qa-installed-host.py --app /Applications/Wizard.app \
  --data-home "$OWNED_EXTERNAL_DATA_HOME" \
  --evidence "$NEW_EXTERNAL_EVIDENCE_DIRECTORY" \
  --notify "$COMPILED_UPDATE_QA_NOTIFY"
```

This tool requires an already prepared, stopped QA disk. It verifies the exact
embedded Host PID/executable/DataHome, `running` state and both native bridge
health endpoints. It does not assert guest preservation or update success.
It refuses other MVP processes/occupied ports. Preferences are saved privately,
restored only while still owned, and compared as decoded plists. An initializer
`mkdirat` stall without status/VZ evidence is sampled and can be retired; a live
VM is only asked to stop gracefully. Unfinished cleanup is a hard failure, not a
pass receipt. A final combined release still needs authenticated native + guest
installation, state-preservation, relaunch and rollback acceptance.

## Bluetooth input: explicit unresolved choice

The donor `5d65d996014eb7c7dedb93b59a10a8815deba194` is built only by the legacy
`macos` product. It gives an explicit device selection precedence over its
System Default Bluetooth → built-in → wired policy. `next/mac/build.sh` does
not compile that policy. Current MVP meeting `MicSource` uses AVAudioEngine's
macOS default input; it has no persisted explicit-device-vs-automatic contract.
WK voice uses a separate getUserMedia route. Neither changing the system default
nor porting only the legacy files fixes both paths safely.

**Choice required:** should MVP introduce a visible `Microphone` choice shared
by meetings and voice, with `Automatic (preserve Bluetooth music)` as its new
default, plus `Follow macOS input` and explicit device UID choices? An explicit
choice (including Bluetooth) must win; a disappeared explicit device must be
shown rather than silently reinterpreted. Existing guest selections such as
`MacBook Pro Microphone` must remain untouched. Until that contract is selected
and adapted to both AVAudioEngine and WK, leave routing unchanged and do not
claim Bluetooth avoidance in this MVP. Physical music/mic QA remains separate.
