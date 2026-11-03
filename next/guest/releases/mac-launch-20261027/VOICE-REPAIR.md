# Bounded selected local voice repair

REUSE: immutable security-remediated engine, its Python/ORT/ONNX-ASR versions,
OCI exporter and security probes, WAM lifecycle, cached four pinned INT8 graphs,
production core and pristine stopped Slim disk. EXTEND: one Speaches executor,
selected-image package/resolution, normal component transaction and rollback.
No provider/model change, stock Hermes patch, owner activation or release.

`package-voice-image.py --output NEW_DIRECTORY` is native ARM/macOS work only.
It refuses a different immutable predecessor or source hash, changes no packages
or runtime image configuration, deletes stale bytecode and repeats inherited
trust-client probes under read-only/unprivileged execution. It publishes nothing.
The owning `package-security-image.py` dispatches `voiceOverlay` targets here.

`resolve-voice-package.py --receipt REAL_RESULT --native PINNED_NATIVE_GUEST
--output NEW_PAYLOAD` verifies the actual OCI archive and writes a selected
contract, image package descriptor, code members and transport archive. It does
not mutate the predecessor factory stage. No new digest belongs in source before
this receipt exists. Optional security-plan output remains explicitly incomplete
until the owning full image closure/preflight is rerun. For factory adoption copy
the generated selected-engine.json to preparation/voice-selected-engine.json;
finalize_voice checks it against the resolved plan. All non-voice pins remain.

The normal stack sealer consumes WORKSPACE/voice-package/{selected-engine.json,
voice-package.json,voice-engine.oci.tar}; these all enter runtime-bom.json. Normal
upgrade dispatches to voice/update.py only when that descriptor exists. The same
bounded authenticated production component entrypoint is:

    python3 PAYLOAD/overlay/opt/wizard/voice/install.py PAYLOAD --apply
    python3 PAYLOAD/overlay/opt/wizard/voice/install.py PAYLOAD --rollback

The image owner takes the coordinator lock, verifies the previous selected
binding, fences Retry before mixed code, preserves the old digest for rollback,
loads only the NEW authenticated immutable archive, and calls normal WAM stop /
start. The strict code installer still rejects an unexplained selected-image
change. An interrupted image transaction refuses apply until authenticated
rollback; a rolled-back journal is retained before a fresh apply. Rollback fences
before old executable restoration, clears historical failed-unit status and
restores files atomically. No old voice writer is re-enabled or run. No images,
apps, networks or volumes are pruned.

The old ARM failure did not save ConditionResult/ActiveState. It is not proof
that an obsolete writer ran. Diagnostics must retain the original FAIL and log
actual invocation timestamps/ID/MainPID/unit conditions plus output/config
hashes before assertions; condition-skipping does not itself clear failed state.

ONNX-ASR 0.7's `encoder-model?int8.onnx` is a Path.glob pattern: '?' matches '.'.
It is not proof of literal filename incompatibility. The adapter uses public
load_model('nemo-conformer-tdt', path=exact_snapshot, quantization='int8') after
exact file/hash validation, deliberately ignoring refs/main. Normal Service
15d501a requests verbose_json for task-bearing ASR entries, so the adapter emits
text/duration/English without invented segments or confidence scores. Service
speechText preserves text when segments is absent/null.

Source fakes are not native/image/ARM proof. Runtime acceptance requires the
new secured image to transcribe synthetic audio through /wizard/voice/transcribe
in a fresh admitted clone, repeat/concurrent Retry without container churn, and
actual rollback + Retry/direct starts with no old-writer invocation/output
change. Reset/reload and fresh condition timestamps are checked, not only an
old ConditionResult. Preserve all failed clones stopped and bind cleanup to
current-boot powerdown and closed-disk descriptors. Full factory/native App/UI
release acceptance is separate from this narrow component/core proof.
