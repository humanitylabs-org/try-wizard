#!/usr/bin/env python3
"""Extract unchanged production implementations; compile ONLY in durable Thales job."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

PRODUCTION = 'c7952d68e6a61da74b1e26485293cb7b5d881c7b'
SOURCES = ['next/mac/Host/main.swift', 'next/mac/Shared/Shared.swift',
           'next/mac/Shared/UpdateContract.swift', 'next/mac/Shared/DiskIdentity.swift',
           'next/mac/Shared/GuestPatchCommand.swift', 'next/mac/App/WizardGuestActivation.swift',
           'next/mac/App/WizardUpdater.swift', 'next/guest/cold-bootstrap.py',
           'next/guest/upgrade-mvp-stack.py', 'next/guest/cold-config.py',
           'next/guest/stack-preservation.py',
           'next/guest/overlay/opt/wizard/bin/wizard-product-configure']


def generate(source, out):
    out.mkdir(parents=True, exist_ok=False)
    manifest = {'production': PRODUCTION, 'files': {}, 'extractions': [], 'adapters': []}
    originals = {}
    for name in SOURCES:
        raw = (source/name).read_bytes()
        pinned = subprocess.check_output(['git', '-C', str(source), 'show', PRODUCTION+':'+name])
        if raw != pinned:
            raise RuntimeError('Production source drift: '+name)
        originals[name] = raw.decode()
        manifest['files'][name] = hashlib.sha256(raw).hexdigest()

    def extract(name, start, end, destination, replacements=()):
        full = originals[name]
        a, b = full.index(start), full.index(end)
        text = full[a:b]
        record = {'source': name, 'startLine': full[:a].count('\n')+1,
                  'endLine': full[:b].count('\n'), 'extractedSHA256': hashlib.sha256(text.encode()).hexdigest(),
                  'destination': destination}
        for old, new, reason in replacements:
            if text.count(old) != 1:
                raise RuntimeError('Non-unique adapter: '+reason)
            text = text.replace(old, new)
            manifest['adapters'].append({'destination':destination, 'reason':reason, 'old':old, 'new':new})
        (out/destination).write_text(text)
        record['generatedSHA256'] = hashlib.sha256(text.encode()).hexdigest()
        manifest['extractions'].append(record)

    # No NSApplication, menu, notification, NSWorkspace or remote-shell TCP listener.
    host = originals[SOURCES[0]]
    listener = host[host.index('    // Guest -> Mac:'):host.index('    private var coldSerial:')]
    extract(SOURCES[0], 'import AppKit', '// MARK: - Menu bar', 'VM.swift', [
        ('import AppKit', 'import Foundation', 'CLI VM slice uses Foundation types only; do not link AppKit'),
        (listener,
        '    func listener(_ listener: VZVirtioSocketListener, shouldAcceptNewConnection connection: VZVirtioSocketConnection, from socketDevice: VZVirtioSocketDevice) -> Bool { return false }\n\n',
        'Refuse guest URL-opening I/O instead of invoking desktop NSWorkspace')])
    shared = originals[SOURCES[1]]
    old = shared[shared.index('    static var supportDir: URL {'):shared.index('    static var osDir: URL')]
    new = '    static var supportDir: URL { URL(fileURLWithPath: ProcessInfo.processInfo.environment["WIZARD_HEADLESS_DATA"]!) }\n'
    (out/'Shared.swift').write_text(shared.replace(old,new))
    manifest['adapters'].append({'destination':'Shared.swift','reason':'Explicit isolated data root; no preference reads/writes','old':old,'new':new})
    for name in SOURCES[2:6]:
        text = originals[name]
        if name.endswith('/WizardGuestActivation.swift'):
            assert text.count('import AppKit') == 1
            text = text.replace('import AppKit','import Foundation')
            manifest['adapters'].append({'destination':Path(name).name,
                'reason':'Activation uses only Foundation types; implementation unchanged',
                'old':'import AppKit','new':'import Foundation'})
        (out/Path(name).name).write_text(text)
    # Exact stopped-admission implementation after adapter-selected consent.
    # Only bundle input is redirected to the already sealed production app.
    full = originals[SOURCES[6]]
    a = full.index('            try ownership.acquire()', full.index('func admitLegacyBootstrap'))
    b = full.index('            WizardGuestActivation.shared.onProgress', a)
    body = full[a:b]
    manifest['extractions'].append({'source':SOURCES[6],'startLine':full[:a].count('\n')+1,
        'endLine':full[:b].count('\n'),'extractedSHA256':hashlib.sha256(body.encode()).hexdigest(),
        'destination':'Admission.swift'})
    body = body.replace('Bundle.main.bundleURL','candidateApp').replace('Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion")','"307"')
    manifest['adapters'].append({'destination':'Admission.swift','reason':'Sealed candidate bundle instead of CLI bundle; no physical consent claim'})
    (out/'Admission.swift').write_text('import Foundation\nimport Darwin\n@MainActor func admitStopped() throws {\nlet ownership = WizardDiskOwnership(); defer { ownership.release() }\n'+body+'\n}\n')
    shutil.copyfile(Path(__file__).with_name('main.swift'), out/'main.swift')
    manifest['generated'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.swift')}
    (out/'provenance.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path,required=True); p.add_argument('--out',type=Path,required=True)
    p.add_argument('--extract-only',action='store_true'); a=p.parse_args()
    generate(a.source,a.out)
    if a.extract_only: return
    if not str(a.out.resolve()).startswith('/Volumes/ThalesMedia/'):
        raise RuntimeError('Compilation must use durable Thales external-volume worker')
    (a.out/'module-cache').mkdir()
    cmd=['xcrun','swiftc','-O','-target','arm64-apple-macos14.0','-swift-version','5',
         '-module-cache-path',str(a.out/'module-cache'),
         '-framework','Foundation','-framework','Virtualization','-framework','CryptoKit',
         *map(str, sorted(a.out.glob('*.swift'))),'-o',str(a.out/'headless-cold')]
    subprocess.run(cmd,check=True)
    ent=Path(__file__).with_name('entitlements.plist')
    subprocess.run(['codesign','--force','--sign','-','--entitlements',str(ent),str(a.out/'headless-cold')],check=True)
    subprocess.run(['codesign','--verify','--strict',str(a.out/'headless-cold')],check=True)

if __name__=='__main__': main()
