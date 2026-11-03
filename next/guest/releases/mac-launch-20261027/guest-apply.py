#!/usr/bin/env python3
"""Inside only the disposable retained-factory clone. Frozen RC first, Mac layers second."""
import argparse, hashlib, json, os, re, shutil, sqlite3, subprocess
from pathlib import Path
import local_oci as oci
import guest_docker_store as store
ROOT=Path('/mnt/launch');WORK=ROOT/'assembly-work'

def run(argv,**kw):
    # stream=True: the child writes straight into apply.log, so a failing installer leaves its own reason there.
    if kw.pop('stream',False):subprocess.run(list(map(str,argv)),check=True,timeout=kw.pop('timeout',600),**kw);return ''
    return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',600),**kw)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def pristine():
    home=Path('/home/wizard/runtipi/app-data/wizardapps/hermes-agent/data')
    assert os.geteuid()==0 and not Path('/var/lib/wizard/setup.json').exists(),'onboarded guest refused'
    for name in ['auth.json','anon_auth.json','guest_identity.json']:
        p=home/name;assert not p.exists() or not p.stat().st_size,'account identity refused'
    for p in home.glob('*.db'):
        c=sqlite3.connect('file:'+str(p)+'?mode=ro',uri=True)
        for table in ['sessions','messages']:
            if c.execute('select name from sqlite_master where name=?',(table,)).fetchone():assert c.execute('select count(*) from '+table).fetchone()[0]==0
        c.close()
    assert not list(Path('/home/wizard/runtipi/app-data/wizard-os/agents').glob('*/agent.json'))

def install_package(source,dest):
    for member in [source,*source.rglob('*')]:
        if '__pycache__' in member.parts:continue
        assert not member.is_symlink() and (member.is_file() or member.is_dir()),'special overlay member refused'
        target=dest/member.relative_to(source)
        assert not any(x.is_symlink() for x in [target,*target.parents]),'redirected overlay refused'
        if member.is_dir():target.mkdir(parents=True,exist_ok=True);target.chmod(0o755)
        else:target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(member,target);target.chmod(0o755 if member.stat().st_mode&0o111 else 0o644)

def reattach_sealed_wam_checkout(directory,repo,as_user=('sudo','-u','wizard'),evidence=None):
    """The retained factory was sealed with .git stripped and SOURCE_COMMIT written (seal-factory.py).
    get.sh's pinned path needs a git checkout to upgrade in place, so rebuild .git at the sealed
    commit without touching the work tree. If any tracked file differs from the stamp, the tree is
    discarded (with drift evidence) so the installer clones the pinned commit fresh."""
    directory=Path(directory)
    if not directory.exists() or (directory/'.git').exists():return None
    old=(directory/'SOURCE_COMMIT').read_text().strip()
    assert re.fullmatch(r'[0-9a-f]{40}',old),'sealed App Manager has no exact SOURCE_COMMIT'
    g=[*as_user,'git','-C',str(directory)]
    run([*g,'init','-q']);run([*g,'remote','add','origin',repo])
    run([*g,'fetch','-q','origin',old],timeout=900);run([*g,'reset','-q','--mixed','FETCH_HEAD'])
    assert run([*g,'rev-parse','HEAD']).strip()==old
    drift=run([*g,'status','--porcelain','--untracked-files=no']).rstrip()
    if not drift:return old
    # The stamp does not describe the tree, so nothing in it is trusted: record the drift, then remove the
    # tree so get.sh clones the pinned App Manager fresh. Nothing from the unverified tree is reused.
    if evidence is not None:
        Path(evidence).write_text(json.dumps({'sourceCommit':old,'trackedDrift':drift.splitlines(),'action':'removed; pinned installer clones fresh'},indent=2)+'\n')
    shutil.rmtree(directory);assert not directory.exists()
    return 'removed'

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-pristine',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args();pristine()
    if a.check_pristine:print('pristine empty factory verified');return
    assert a.apply
    pins=json.loads((ROOT/'preparation/pins.json').read_text());release=json.loads((WORK/'runtime-release.json').read_text())
    release_dir=Path('/var/lib/wizard/frozen-release');release_dir.mkdir(parents=True,exist_ok=True)
    target=release_dir/(release['version']+'.json');shutil.copy2(WORK/'runtime-release.json',target);assert sha(target)==sha(WORK/'runtime-release.json')
    # get.sh drops to the wizard user before fetching file:// releases; the manifest is public pin data.
    release_dir.chmod(0o755);target.chmod(0o644)
    # Debian workaround from the primary advisory; do not use the retained stale roots to bootstrap HTTPS.
    config=Path('/etc/ca-certificates.conf')
    roots={'mozilla/emSign_ECC_Root_CA_-_G3.crt','mozilla/Comodo_AAA_Services_root.crt'}
    config.write_text('\n'.join('!'+line if line in roots else line for line in config.read_text().splitlines())+'\n')
    run(['update-ca-certificates','--fresh'])
    run(['apt-get','update'],timeout=300)
    run(['apt-get','install','-y','--no-install-recommends','ca-certificates','curl','python3-yaml'],timeout=600)
    plan=json.loads((ROOT/'preparation/security-image-plan.json').read_text());assert plan['complete'] is True
    assert json.loads((ROOT/'security-preflight.json').read_text())['allGuestImagesEnumerated'] is True
    import factory_migrations as migration
    run(['systemctl','disable','--now','wizard-voice.service'])  # retained writer stays inert until final selected-contract transaction
    migration.empty_legacy_state(Path('/home/wizard/runtipi/app-data/wizardapps/wizard-shell/data'))
    migration.clean_overlays(Path('/home/wizard/runtipi'),WORK)
    inherited=store.enable(WORK)
    migration.retire_hidden_managed_runtime(WORK,inherited,run(['docker','image','ls','-q','--no-trunc']).split())
    for selection in plan['targets']:
        row=json.loads((ROOT/selection['receipt']).read_text())
        assert plan['resolutions'][selection['key']]['image']==row['ref']+'@'+row['digest']
        oci.load(ROOT,row)
    helper=plan['resolutions']['helper-python']['image']
    cid=run(['docker','create',helper]).strip()
    try:
        for name in ['uv','uvx']:run(['docker','cp',cid+':/usr/local/bin/'+name,'/usr/local/bin/'+name])
    finally:run(['docker','rm',cid])
    wheel=ROOT/'security-packaging/helper-python/context/certifi.whl'
    assert sha(wheel)==plan['upstreamInputs']['certifi']['sha256']
    pip_wheel=ROOT/'security-packaging/helper-python/context/pip.whl'
    assert sha(pip_wheel)==plan['upstreamInputs']['pip']['sha256']
    run(['python3',ROOT/'preparation/remediate-trust.py','--wheel',wheel,'--pip-wheel',pip_wheel,'--output',WORK/'host-remediation.json'],timeout=600)
    configs=Path('/home/wizard/runtipi/user-config/wizardapps');configs.mkdir(parents=True,exist_ok=True)
    run(['chown','-R','--no-dereference','wizard:wizard',configs])
    run(['python3',ROOT/'preparation/guest-security-apply.py','--prepare'],timeout=1800)
    store.bootstrap(WORK)
    store.verify(WORK,receipt='docker-bootstrap-resolution.json')
    migration.prepare(ROOT,Path('/home/wizard/runtipi'),WORK,run)
    helper=Path('/usr/local/lib/wizard/factory-host-trust.py');helper.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'preparation/factory_migrations.py',helper);helper.chmod(0o755)
    drop=Path('/etc/systemd/system/wizard-firstboot.service.d/30-trust-local-host.conf');drop.parent.mkdir(parents=True,exist_ok=True)
    drop.write_text('[Unit]\nBefore=docker.service\n[Service]\nExecStartPost=/usr/bin/python3 '+str(helper)+'\n')
    run(['python3',helper]);run(['systemctl','daemon-reload'])
    bundle=ROOT/'source-bundles/recorder.bundle'
    expected=json.loads((ROOT/'staged-files.json').read_text())['files']['source-bundles/recorder.bundle']
    assert sha(bundle)==expected, 'frozen recorder bundle changed'
    frozen=Path('/var/lib/wizard/frozen-recorder.git');assert not frozen.exists()
    run(['git','clone','--bare',bundle,frozen])
    assert run(['git','-C',frozen,'cat-file','-t',release['default_apps']['recorder']['commit']]).strip()=='commit'
    run(['chown','-R','--no-dereference','wizard:wizard',frozen])
    rewrite='url.file://'+str(frozen)+'.insteadOf'
    run(['sudo','-u','wizard','git','config','--global',rewrite,'https://github.com/humanitylabs-org/wizard-recorder'])
    installer=ROOT/'final/wam/get.sh';assert sha(installer)==pins['osInstaller']['sha256']
    env={k:v for k,v in os.environ.items() if k not in ['WAM_REF','WAM_IMAGE','WIZARD_SHELL_IMAGE','WIZARD_UX_IMAGE','WIZARD_AGENT_SERVICE_IMAGE']}
    env.update(WIZARD_RELEASE=release['version'],WIZARD_RELEASE_BASE='file://'+str(release_dir),WIZARD_STRICT='1',WIZARD_MODE='fresh',WIZARD_PRIVATE_ACCESS='tailscale')
    for component,key in [('wizard-app-manager','WAM_IMAGE'),('wizard-ux','WIZARD_UX_IMAGE'),('wizard-agent-service','WIZARD_AGENT_SERVICE_IMAGE')]:
        item=release['images'][component];env[key]=item['ref']+'@'+item['digest']
    # The retained base's store tree was written by root (Runtipi's own clone); the pinned WAM runs as
    # wizard and stages private app definitions there. Hand over only store definitions, never app data.
    store_apps=Path('/home/wizard/runtipi/repos/wizardapps/apps')
    if store_apps.is_dir():run(['chown','-R','--no-dereference','wizard:wizard',store_apps])
    reattach_sealed_wam_checkout('/home/wizard/wizard-app-manager',env.get('WAM_REPO','https://github.com/humanitylabs-org/wizard-app-manager'),evidence=WORK/'sealed-wam-drift.json')
    env.update(WIZARD_GITHUB='0',WIZARD_TAILSCALE_WAIT='0',WIZARD_APP_OWNER_LOGINS='owner@wizard.local',WIZARD_APP_MANAGER_HOSTS='127.0.0.1:48023,localhost:48023')
    forwarded=[k+'='+env[k] for k in sorted(env) if k.startswith(('WIZARD_','WAM_'))]
    # Run the frozen bytes directly as wizard: root get.sh re-execs a network installer
    # and only forwards a subset of env (dropping the factory owner route).
    run(['sudo','-iu','wizard','env',*forwarded,'bash',installer],stream=True,stdin=subprocess.DEVNULL,timeout=3600)
    run(['sudo','-u','wizard','git','config','--global','--unset-all',rewrite]);shutil.rmtree(frozen)
    assert run(['sudo','-u','wizard','git','-C','/home/wizard/wizard-app-manager','rev-parse','HEAD']).strip()==pins['finalPins']['wam']
    installed=json.loads(Path('/home/wizard/.wizard-os/release-pins.json').read_text());assert installed==release
    # Every default row is source-pinned in the release; get.sh WIZARD_STRICT reads actual installs back.
    outcome=json.loads(Path('/home/wizard/.wizard-os/release.json').read_text())
    assert outcome.get('status')=='pinned', 'strict installer did not leave a pinned receipt'
    (WORK/'install-outcome.json').write_text(json.dumps(outcome,indent=2)+'\n')
    native=ROOT/'final/native/next/guest'
    install_package(native/'overlay/opt/wizard',Path('/opt/wizard'))
    install_package(ROOT/'final/service/ops/agent-runtime',Path('/opt/wizard/agent-runtime'))
    # Same authenticated stock packaging boundary as retained Mac runtime; no alternate brain/runtime.
    stock=pins['runtimeBuild']['hermesImage'];tag='wizard-hermes:managed-'+pins['finalPins']['native'][:12]
    assert stock==plan['resolutions']['stock']['image']
    # Keep the admitted guard compiler and exact interpreter ABI/paths; Python's certificate fix
    # is the pip/certifi/ensurepip overlay, not an unrelated runtime replacement.
    run(['docker','build','--build-arg','HERMES_IMAGE='+stock,'-t',tag,native/'managed-launch'],timeout=1200)
    image=json.loads(run(['docker','image','inspect',tag]))[0]
    assert image['Architecture']=='arm64' and image['Config']['Labels']['ai.wizards.managed-launch']=='1'
    stock_meta=json.loads(run(['docker','image','inspect',stock]))[0]
    stock_revision=(stock_meta['Config'].get('Labels') or {}).get('org.opencontainers.image.revision')
    assert stock_revision=='f97608f178d1ffeca59860195ab7da295f7c8e5f', 'unknown stock managed-maintenance contract'
    Path('/opt/wizard/managed-runtime.json').write_text(json.dumps({'image':image['Id'],'stock':stock_revision}))
    import sys
    sys.path.insert(0,'/opt/wizard/agent-runtime')
    from managed_maintenance import ManagedMaintenance
    ManagedMaintenance()
    run(['/opt/wizard/bin/wizard-product-configure'])
    run(['sudo','-iu','wizard','wam','fresh-agent','connect'])
    run(['/opt/wizard/bin/wizard-agent-ssh-migrate'])
    run(['/opt/wizard/bin/wizard-runtime-configure'])
    run(['systemctl','daemon-reload']);run(['systemctl','restart','wizard-setup','wizard-local-proxy'])
    containers=json.loads(run(['docker','inspect',*run(['docker','ps','-q']).split()]))
    for key,name in [('service','wizard-agent-service'),('ux','wizard-ux')]:
        wanted=release['images'][name]['ref']+'@'+release['images'][name]['digest']
        expected=json.loads(run(['docker','image','inspect',wanted]))[0]['Id']
        assert any(c['Image']==expected for c in containers),'selected '+key+' not running'
    (WORK/'running-images.json').write_text(json.dumps([{'name':c['Name'],'imageId':c['Image'],'ref':c['Config']['Image']} for c in containers],indent=2)+'\n')
    # Final configuration writers can replace overrides; restore them preserving the managed guard image,
    # restart through WAM, prove actual IDs, then remove every old unused local image/cache from this clone.
    run(['python3',ROOT/'preparation/guest-security-apply.py','--finish'],timeout=3600)
    store.verify(WORK,store.inherited(WORK))
    states=migration.default_states(migration.factory_manager(ROOT,Path('/home/wizard/runtipi')),release)
    (WORK/'default-app-states.json').write_text(json.dumps(states,indent=2)+'\n')
    store_data=json.loads(run(['sudo','-iu','wizard','wam','store-data']))
    assert store_data['state']=='ready', 'local App Store data not ready: '+json.dumps(store_data)
    (WORK/'store-data-status.json').write_text(json.dumps(store_data,indent=2)+'\n')
    connection=json.loads(run(['sudo','-iu','wizard','wam','fresh-agent','status']))
    assert connection['ok'] is True, 'fresh-agent connection failed: '+json.dumps(connection['checks'])
    (WORK/'fresh-agent-status.json').write_text(json.dumps(connection,indent=2)+'\n')
    run(['sudo','-iu','wizard','wam','doctor'],stream=True)
    # Mandatory on host and EVERY running container's actual mounted trust stores, not fresh docker runs.
    run(['python3',ROOT/'preparation/security-closure.py','--guest','--output',WORK/'security-guest.json'],timeout=3600)
    pristine();(WORK/'applied.json').write_text(json.dumps({'releaseSha256':sha(target),'sources':pins['finalPins'],'pristine':True,'securityClosure':True,'publishing':False},indent=2)+'\n')

if __name__=='__main__':main()
