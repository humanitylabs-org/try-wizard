"""Selected local voice reconciliation. Never selects an image from Hermes.

WAM owns lifecycle. This module owns only validation, the exact old writer
migration, and bounded public readiness. No Docker mutation/pull or model fetch.
"""
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import time
import urllib.error
import urllib.request

MODEL = 'istupakov/parakeet-tdt-0.6b-v2-onnx'
SELECTION = Path('/opt/wizard/voice/selected-engine.json')
LOCK = Path('/var/lib/wizard/voice-reconcile.lock')
LEGACY_MARKER = '# Written by Try Wizard (wizard-apps fetch-voice): local Parakeet voice.'


class Refusal(RuntimeError):
    """Fixed public actionable reason, never a runtime response or credential."""


def selection(path=SELECTION):
    for member in (path, *path.parents):
        s = member.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise Refusal('Local voice selection is not protected. Reinstall the voice update.')
    return validate_selection(json.loads(path.read_text()))


def validate_selection(value):
    if (value.get('schema') != 1 or value.get('api') != 'speaches-0.9'
            or value.get('model') != MODEL or value.get('provider') != 'local'
            or value.get('revision') != '0bbb45a3365852604aef28b538a8f066f4ccaa85'
            or value.get('quantization') != 'int8'
            or set(value.get('bindings', {})) != {'transcriber', 'transcriber-engine'}
            or value['bindings']['transcriber-engine'] != value.get('image')
            or not all(re.fullmatch(r'[a-z0-9./_-]+@sha256:[0-9a-f]{64}', ref)
                       for ref in value['bindings'].values())):
        raise Refusal('Voice engine contract needs a compatible update.')
    return value


def atomic(path, raw, mode=0o644):
    tmp = path.with_name('.' + path.name + '.' + str(os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        tmp.unlink(missing_ok=True)


def migrate_override(path, selected):
    """Migrate only the exact known old writer, never arbitrary user/security YAML.

    Preserve original bytes in a content-addressed sibling. Unknown fields/tags
    are a refusal, not an invitation to reconstruct or weaken Compose settings.
    """
    import yaml
    if not path.exists():
        raise Refusal('Selected voice image binding is missing. Reinstall the voice update.')
    if path.is_symlink():
        raise Refusal('Voice image binding is redirected. Repair it before retrying.')
    raw = path.read_bytes()
    doc = yaml.safe_load(raw)
    if not isinstance(doc, dict):
        raise Refusal('Voice image binding is unsupported. Reinstall the voice update.')
    engine = doc.get('services', {}).get('transcriber-engine', {})
    if raw.startswith(LEGACY_MARKER.encode()):
        expected = {'services': {'transcriber-engine': {
            'image': engine.get('image'), 'pull_policy': 'missing', 'user': '1000:1000',
            'entrypoint': ['sh', '/voice/start.sh'], 'command': [],
            'volumes': ['/opt/wizard/voice:/voice:ro', '${APP_DATA_DIR}/data/voice:/data']}}}
        if doc != expected:
            raise Refusal('Unrecognized legacy voice settings. Review them before retrying.')
        backup = path.with_name('docker-compose.legacy-' + hashlib.sha256(raw).hexdigest() + '.bak')
        if backup.exists():
            if backup.is_symlink() or backup.read_bytes() != raw:
                raise Refusal('Voice migration backup conflicts. Review it before retrying.')
        else:
            atomic(backup, raw, 0o600)
        # No other settings existed in this exact writer. Recipe security remains
        # authoritative; do not replace it with a new entrypoint or runtime.
        doc = binding_document(selected)
        atomic(path, yaml.safe_dump(doc, sort_keys=False).encode())
        return True
    if doc != binding_document(selected):
        raise Refusal('Voice settings differ from the security selection. Review the bindings before retrying.')
    return False


def binding_document(selected):
    return {'services': {service: {'image': image, 'pull_policy': 'if_not_present'}
                         for service, image in sorted(selected['bindings'].items())}}


def contract_from_plan(plan, bindings):
    chosen = {b['service']: plan['resolutions'][b['target']]['image']
              for b in bindings['bindings'] if b['app'] == 'transcriber'}
    if set(chosen) != {'transcriber', 'transcriber-engine'}:
        raise Refusal('Incomplete security-selected voice bindings.')
    return {'schema': 1, 'api': 'speaches-0.9', 'provider': 'local',
            'image': chosen['transcriber-engine'], 'bindings': chosen, 'model': MODEL,
            'revision': '0bbb45a3365852604aef28b538a8f066f4ccaa85', 'quantization': 'int8'}


def inspected(docker, *args):
    result = docker(*args)
    if result.returncode:
        raise Refusal('Could not verify the selected local voice engine. Retry after App Manager is ready.')
    return json.loads(result.stdout)


def engine(docker, expected):
    result = docker('ps', '-aq', '--filter', 'label=com.docker.compose.service=transcriber-engine')
    if result.returncode:
        raise Refusal('Could not inspect local voice. Retry after App Manager is ready.')
    ids = result.stdout.split()
    if len(ids) > 1:
        raise Refusal('More than one local voice engine exists. Review App Manager before retrying.')
    if not ids:
        return None
    row = inspected(docker, 'inspect', ids[0])[0]
    if row['Image'] != expected:
        raise Refusal('Running voice image differs from the security selection. Install the selected voice update.')
    config = row['Config']
    # Detect the old Hermes entrypoint even if a mutable tag was reused.
    if config.get('Entrypoint') == ['sh', '/voice/start.sh']:
        raise Refusal('Legacy voice runtime is still active. Install the selected voice update.')
    return row


def origin(row):
    addresses = sorted({v['IPAddress'] for v in row['NetworkSettings']['Networks'].values() if v.get('IPAddress')})
    if len(addresses) != 1:
        raise Refusal('Voice network is ambiguous. Review App Manager before retrying.')
    address = ipaddress.ip_address(addresses[0])
    if address.version != 4 or not address.is_private:
        raise Refusal('Voice engine is not on its private network.')
    return 'http://' + str(address) + ':8000'


def get_json(url):
    # Explicitly ignore ambient HTTP proxies: engine traffic stays in the VM.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=10) as response:
        raw = response.read(65537)
        if response.status != 200 or len(raw) > 65536:
            raise Refusal('Voice engine response is unsupported. Install a compatible voice update.')
        return json.loads(raw)


def health(row, get=get_json):
    base = origin(row)
    h = get(base + '/health')
    if h != {'message': 'OK'}:
        raise Refusal('Voice engine contract is unsupported. Install a compatible voice update.')
    models = get(base + '/v1/models')
    if not isinstance(models, dict) or not isinstance(models.get('data'), list):
        raise Refusal('Voice model contract is unsupported. Install a compatible voice update.')
    entries = [m for m in models['data'] if isinstance(m, dict)]
    speech = ([m for m in entries if m.get('task') == 'automatic-speech-recognition']
              if any('task' in m for m in entries) else entries)
    if len(speech) != 1 or speech[0].get('id') != MODEL:
        raise Refusal('The required Parakeet model is not the only selected speech model. Review its compatible voice package.')
    # A model listing is only preparation evidence, not transcription proof.
    return {'status': 'ok', 'model': MODEL, 'provider': 'local'}


def verify_model_runtime(docker, row):
    # A matching API model name must not silently select FP32, another revision,
    # or a library cache populated from mutable main. This is a read-only probe.
    probe = r'''import hashlib, inspect
from pathlib import Path
from speaches.executors import parakeet
assert hashlib.sha256(Path(parakeet.__file__).read_bytes()).hexdigest() == '4ae97f207b41f21d665e2e99408804cab0937a5d7a8c08dae136e1f1c533151b', 'unsupported_source'
assert parakeet.WIZARD_PINNED_PARAKEET == 1, 'stale_bytecode'
parakeet.validated_snapshot(parakeet.MODEL_ID)
print('verified-parakeet-int8-v1')'''
    result = docker('exec', row['Id'], 'python', '-c', probe)
    if result.returncode or result.stdout.strip() != 'verified-parakeet-int8-v1':
        raise Refusal('The selected voice engine cannot verify the required pinned Parakeet runtime. Install a compatible hardened voice package.')


def reconcile(c, cli, docker, installed, selected, progress, deadline=180):
    for ref in selected['bindings'].values():
        metadata = inspected(docker, 'image', 'inspect', ref)[0]
        if ref not in (metadata.get('RepoDigests') or []):
            raise Refusal('Selected voice image digest is unavailable locally. Install the voice package; no fallback was used.')
    image = inspected(docker, 'image', 'inspect', selected['image'])[0]
    expected = image['Id']  # Compare like-for-like daemon IDs (OCI/containerd may use manifest IDs).
    if selected['image'] not in (image.get('RepoDigests') or []):
        raise Refusal('Selected voice image digest is unavailable locally. Install the voice package; no fallback was used.')
    path = c.runtipi_root / 'user-config' / cli.STORE / 'transcriber' / 'docker-compose.yml'
    migrate_override(path, selected)
    row = engine(docker, expected)
    urn = 'transcriber:' + cli.STORE
    if 'transcriber' not in installed(c):
        cli.install(c, 'transcriber', {'TRANSCRIBER_MODEL': MODEL})
    elif row is None or not row['State']['Running']:
        rt = c.runtipi()
        rt.req('POST', '/app-lifecycle/' + urn + '/start', {}, timeout=300)
        rt.wait_status(urn, {'running'}, timeout=deadline)
    end = time.monotonic() + deadline
    while True:
        row = engine(docker, expected)
        if row and row['State']['Running']:
            try:
                result = health(row)
                verify_model_runtime(docker, row)
                loaded = get_json(origin(row) + '/api/ps')
                if MODEL not in loaded.get('models', []):
                    raise Refusal('The required Parakeet model is not loaded. Install its compatible voice package.')
                # Read image identity again after HTTP; never accept a replaced engine.
                after = engine(docker, expected)
                if not after or after['Id'] != row['Id']:
                    raise Refusal('Voice engine changed during preparation. Retry after App Manager settles.')
                return result
            except (OSError, urllib.error.URLError):
                pass
        if time.monotonic() >= end:
            raise Refusal('Local voice did not start in time. Check App Manager, then retry.')
        progress(state='preparing', detail='starting selected local voice engine', total=0, downloaded=0)
        time.sleep(2)


def run(c, cli, docker, installed, progress, contract=SELECTION, lock=LOCK):
    # The parent is protected and created by firstboot/installer. No lock unlink:
    # all concurrent callers contend on the same inode until the kernel closes it.
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.getuid():
            raise Refusal('Local voice lock needs repair before retrying.')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {'busy': True}
        try:
            selected = selection(contract)
            progress(state='preparing', detail='checking selected local voice', downloaded=0, total=0)
            result = reconcile(c, cli, docker, installed, selected, progress)
            progress(state='ready', model=MODEL, provider='local', downloaded=0, total=0)
            return result
        except Refusal as exc:
            progress(state='error', detail=str(exc), downloaded=0, total=0)
            return {'error': str(exc)}
        except Exception:
            progress(state='error', detail='Could not prepare local voice. Check App Manager and retry.', downloaded=0, total=0)
            return {'error': 'voice_preparation_failed'}
    finally:
        os.close(fd)
