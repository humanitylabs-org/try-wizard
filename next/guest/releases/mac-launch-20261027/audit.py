#!/usr/bin/env python3
"""Read-only, fail-closed launch admission. No VM before A/B/C and execution evidence.
--admit-and-build is parent worker only. No merge, signing, publishing or feed update.
"""
import argparse, collections, hashlib, json, os, re, subprocess, sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
SHA=re.compile(r'[0-9a-f]{40}\Z');DIGEST=re.compile(r'[0-9a-f]{64}\Z');IMAGE=re.compile(r'sha256:[0-9a-f]{64}\Z')

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def inspect_preparation(manifest,queue):
    errors=[];loaded={}
    for key,spec in [('mapping',manifest['queue'].get('mapping')),('candidate',manifest.get('wizardOsCandidate'))]:
        target=(HERE/(spec or {}).get('path','.missing')).resolve()
        if not spec or not target.is_relative_to(HERE.resolve()) or not target.is_file() or digest(target)!=spec.get('sha256'):errors.append(key+' missing or digest mismatch')
        else:loaded[key]=json.loads(target.read_text())
    mapping=loaded.get('mapping')
    if mapping:
        rows=mapping.get('entries',[])
        if mapping.get('sourceSelectionSha256')!=hashlib.sha256(json.dumps(manifest['finalPins'],sort_keys=True).encode()).hexdigest():errors.append('queue mapping selects different final pins')
        if mapping.get('queueSha256')!=queue['queueSha256'] or len(rows)!=queue['entryCount']:errors.append('queue mapping snapshot mismatch')
        if [r.get('id') for r in rows]!=list(range(1,queue['entryCount']+1)):errors.append('queue mapping IDs must be complete, ordered and unique')
        if [(r.get('queueLine'),r.get('entry')) for r in rows]!=[(r['queueLine'],r['entry']) for r in queue['entries']]:errors.append('queue mapping altered original queue entries')
        if dict(collections.Counter(r.get('status') for r in rows))!=mapping.get('counts'):errors.append('queue mapping declared counts disagree')
        allowed={'source-carried','carried-mandatory-security-gate','deferred-to-next-release','superseded','no-guest-change'}
        for row in rows:
            if row.get('status') not in allowed:errors.append('queue undecided: '+str(row.get('id')))
            if row.get('status')=='deferred-to-next-release' and not row.get('reason'):errors.append('queue deferral missing reason')
            for c in row.get('components',[]):
                if c.get('pinnedCommit')!=manifest['finalPins'].get(c.get('component')):errors.append('queue mapping component pin mismatch: '+str(row.get('id')))
        for key in [80,81]:
            match=[r for r in rows if r['id']==key]
            if len(match)!=1 or match[0].get('decision')!='carry' or match[0].get('status') not in {'source-carried','carried-mandatory-security-gate'}:errors.append('mandatory queue requirement not carried: '+str(key))
    candidate=loaded.get('candidate')
    if candidate:
        base=candidate.get('baseRelease',{});target=(HERE/base.get('snapshot','.missing')).resolve()
        if not target.is_relative_to(HERE.resolve()) or not target.is_file() or digest(target)!=base.get('sha256'):errors.append('candidate base stable snapshot digest mismatch')
        for key,app in [('wam','wizard-app-manager'),('service','wizard-agent-service'),('ux','wizard-ux')]:
            if candidate.get('components',{}).get(app,{}).get('commit')!=manifest['finalPins'][key]:errors.append('candidate component pin mismatch: '+key)
        if candidate.get('default_apps',{}).get('recorder',{}).get('commit')!=manifest['finalPins']['recorder']:errors.append('candidate Recorder pin mismatch')
        if candidate.get('status')!='factory-bootstrap-ready':errors.append('IMAGE_DIGESTS_PENDING: Wizard OS source RC is not yet an executable factory bootstrap release')
        if candidate.get('publish') is not False or candidate.get('promote') is not False:errors.append('release publishing/promoting is forbidden')
    return errors

def inspect(manifest,root):
    errors=[]
    queue=json.loads((HERE/manifest['queue']['manifest']).read_text());errors+=inspect_preparation(manifest,queue)
    if digest(HERE/manifest['stable']['manifest'])!=manifest['stable']['sha256']:errors.append('stable release snapshot digest mismatch')
    if len(queue['entries'])!=manifest['queue']['entryCount']:errors.append('queue coverage count mismatch')
    if queue['queueSha256']!=manifest['queue']['sha256']:errors.append('queue snapshot identity mismatch')
    for key,source in manifest['sourceInputs'].items():
        if not SHA.fullmatch(source.get('commit','')):errors.append('invalid exact source pin: '+key)
    for key,pin in manifest['finalPins'].items():
        if not isinstance(pin,str) or not SHA.fullmatch(pin):errors.append('unresolved final pin: '+key)
    assembly=manifest.get('assembly') or {};base=assembly.get('base') or {};execution=manifest.get('execution') or {}
    if assembly.get('mode')!='retained-build-307-factory-adapter' or not DIGEST.fullmatch(base.get('sha256','')):errors.append('ASSEMBLY_BASE_IDENTITY: exact retained build-307 factory required')
    if execution.get('recipe')!='preparation/assemble.py' or execution.get('argv')!=['/opt/homebrew/bin/python3','preparation/assemble.py','--stage-root','.','--execute'] or not DIGEST.fullmatch(execution.get('sha256','')):errors.append('reviewed complete assembly recipe is not pinned')
    for key in ['wam','service','ux']:
        image=assembly.get('images',{}).get(key,{})
        if image.get('sourceCommit')!=manifest['finalPins'][key] or not IMAGE.fullmatch(image.get('digest','')):errors.append('IMAGE_DIGESTS_PENDING: '+key)
    if root is None:
        errors+=['SOURCE_VERIFICATION_V5: staged passing full-source receipt required','SECURITY_IMAGE_CLOSURE: staged all-image TLS evidence required']
        return sorted(set(errors))
    root=root.resolve()
    def record(path):
        target=(root/path).resolve()
        if not target.is_relative_to(root) or not target.is_file():return None
        return json.loads(target.read_text())
    checks=record('source-checks-v5/result.json')
    required={'linux-create','linux-full','linux-logs','factory-pins','phone','stock-builder','factory-admission'}
    if not checks or checks.get('version')!=5 or checks.get('passed') is not True or checks.get('finalPins')!=manifest['finalPins'] or not required.issubset({r.get('key') for r in checks.get('commands',[])}) or any(r.get('returncode')!=0 for r in checks.get('commands',[])):errors.append('SOURCE_VERIFICATION_V5: exact final-pin full source checks have not passed')
    security=record('security-preflight.json');plan=json.loads((HERE/'security-image-plan.json').read_text())
    if plan.get('complete') is not True or not plan.get('images') or not security or security.get('passed') is not True or security.get('allGuestImagesEnumerated') is not True or set(security.get('images',[]))!=set(plan.get('images',[])) or not security.get('checks') or any(r.get('returncode')!=0 for r in security.get('checks',[])):errors.append('SECURITY_IMAGE_CLOSURE: host/default/inherited CA, certifi and Node remediation not proven')
    # Schema2 binds exact real output receipts, image identities and this immutable plan, not only a set of names.
    if plan.get('schema')==2:
        try:
            import importlib.util
            spec=importlib.util.spec_from_file_location('security_closure_admission',HERE/'security-closure.py');assert spec and spec.loader
            closure=importlib.util.module_from_spec(spec);spec.loader.exec_module(closure)
            actual,resolutions=closure.resolve_plan(plan,root,manifest)
            assert security and security.get('schema')==2 and security.get('planSha256')==digest(HERE/'security-image-plan.json')
            assert actual==plan['images'] and resolutions==plan['resolutions'] and security.get('resolutions')==resolutions
            assert sorted(r['target'] for r in security['checks'])==actual
        except (AssertionError,KeyError,OSError,ValueError,StopIteration):errors.append('SECURITY_IMAGE_CLOSURE: exact per-target receipts/plan hash/probe coverage mismatch')
    else:errors.append('SECURITY_IMAGE_CLOSURE: concrete schema2 image resolution plan required')
    ci=record('evidence/ux-final-ci.json')
    if not ci or ci.get('headSha')!=manifest['finalPins']['ux'] or ci.get('conclusion')!='success':errors.append('UX_FINAL_HEAD_CI: accepted baseline must have exact-head green CI')
    for key in ['wam','service','ux']:
        receipt=record('image-packaging/'+key+'/result.json');selected=assembly.get('images',{}).get(key,{})
        if not receipt or receipt.get('sourceCommit')!=manifest['finalPins'][key] or receipt.get('pullVerified') is not True or receipt.get('digest')!=selected.get('digest') or receipt.get('ref')!=selected.get('ref'):errors.append('IMAGE_DIGESTS_PENDING: no matching pull-verified '+key+' output')
    recipe=(root/execution.get('recipe','.missing')).resolve()
    if not recipe.is_relative_to(root) or not recipe.is_file() or digest(recipe)!=execution.get('sha256'):errors.append('assembly recipe missing or digest mismatch')
    for name,pin in manifest['finalPins'].items():
        stamp=record('final/'+name+'/.wizard-source.json')
        if not stamp or stamp.get('commit')!=pin:errors.append('staged final source identity mismatch: '+name)
    installer=root/'final/wam/get.sh'
    expected_url='https://raw.githubusercontent.com/humanitylabs-org/wizard-app-manager/'+manifest['finalPins']['wam']+'/get.sh'
    if manifest['osInstaller']['url']!=expected_url or not installer.is_file() or digest(installer)!=manifest['osInstaller']['sha256']:errors.append('OS_SH_IDENTITY: frozen installer source/hash mismatch')
    native=root/'final/native';provision=native/'next/guest/overlay/opt/wizard/bin/wizard-provision'
    if not provision.is_file() or '-u WAM_REF WIZARD_RELEASE=' not in provision.read_text():errors.append('factory provisioner bypasses frozen release selection')
    # Service #64 must actually exist in the selected archive, not just queue prose.
    for rel in ['server/service.mjs','server/hermes-http-readers.mjs','server/read-human-sessions.py']:
        target=root/'final/service'/rel
        expected=manifest.get('service64Proof',{}).get(rel)
        if not target.is_file() or not expected or digest(target)!=expected:errors.append('SERVICE_64_ALLOWLISTS: missing or changed '+rel)
    inventory=record('staged-files.json')
    if not inventory:errors.append('staged file inventory missing')
    else:
        for name,expected in inventory['files'].items():
            target=root/name
            if not target.resolve().is_relative_to(root) or target.is_symlink() or not target.is_file() or digest(target)!=expected:errors.append('staged file mismatch: '+name)
        for name,target in inventory.get('symlinks',{}).items():
            path=root/name
            if not path.is_symlink() or os.readlink(path)!=target:errors.append('staged symlink mismatch: '+name)
    # Big base hash already read back on Thales and is rechecked by assembly immediately before cloning.
    if not Path(os.path.expandvars(base.get('path','.missing'))).is_file():errors.append('ASSEMBLY_BASE_IDENTITY: retained image unavailable')
    return sorted(set(errors))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage-root',type=Path);p.add_argument('--admit-and-build',action='store_true');a=p.parse_args()
    manifest=json.loads((HERE/'pins.json').read_text());errors=inspect(manifest,a.stage_root)
    if a.admit_and_build and (sys.platform!='darwin' or a.stage_root is None or not a.stage_root.resolve().is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media')))):errors.append('heavy rebuild requires the Thales external-volume worker')
    print(json.dumps({'status':'blocked' if errors else 'admitted','blockers':errors,'queueEntries':manifest['queue']['entryCount'],'publishing':False,'buildStarted':not errors and a.admit_and_build},indent=2))
    if errors:return 2
    if not a.admit_and_build:return 0
    env={**os.environ,'SIGN_IDENTITY':'-'}
    return subprocess.run(manifest['execution']['argv'],cwd=a.stage_root,env=env,check=False).returncode

if __name__=='__main__':raise SystemExit(main())
