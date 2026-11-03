# Voice installer first-failure observation

REUSE: the already compiled production core, existing read-only pristine guest,
accepted secured voice package, native lease and graceful-stop/console helpers.
EXTEND: the former external A3 runtime harness with a diagnostic-only first
installer boundary and byte-exact stream identities plus safe failure projection.
No production installer, image, graph, provider or model change.

`voice-installer-diagnostic.py` runs exactly one ordinary selected-image `--apply`
in a fresh synthetic guest. It records the real exit/timeout, bounded sanitized
stdout/stderr tails, original stream byte counts/SHA256 and source-bound traceback
file/function/line locations. Unknown text, source lines, argv and exception
payloads remain withheld; exact fixed source errors and WAM/yaml import failures
are allowed. A find-spec-only probe uses the lifecycle account/HOME/interpreter
route without injecting a search path, importing Config or touching auth.

`voice-installer-diagnostic-thales.py` is parent-admitted only. Its sealed packet
must include the unchanged `r4_runner.py`, exact real successful security
completion and full file/hash/mode manifest. `--preflight` performs bounded
read-only checks; it never starts a VM or rehashes the large image archive.
Execution retains the full existing payload hashes under the heavy lease, clones
the pristine baseline afresh and preserves shutdown, current-boot witness,
descriptor and baseline metadata guards. It never reuses a failed clone.

Both observation outcomes (installer error or unexpected success) STOP before
Retry, transcription, explicit rollback or repetition. Production apply retains
its own ordinary failure recovery. The guest and host intentionally exit nonzero;
`diagnosticCompleted` means capture completed, not acceptance. `success`,
`fullAcceptance` and `voiceTranscriptionAccepted` remain false, with parent review
required. There is no owner app/GUI launch, host image import, rebuild, publication
or owner activation.

Fast source-only regression command (no Docker, network or VM):

```sh
python3 -B next/guest/tests/test_voice_installer_diagnostic.py
```

This regression does not establish the historical A3 root cause or native runtime
acceptance. Admit only an exact fresh sealed parent packet, then diagnose from
its actual captured installer evidence before changing product behavior.
