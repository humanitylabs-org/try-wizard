#!/usr/bin/env python3
"""Inside only the disposable retained-factory clone. Frozen RC first, Mac layers second."""
import argparse, hashlib, json, os, shutil, sqlite3, subprocess
from pathlib import Path
import local_oci as oci
ROOT=Path('/mnt/launch');WORK=ROOT/'assembly-work'

def run(argv,**kw):return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',600),**kw)
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

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-pristine',action='store_true');p.add_argument('--apply',action='store_true');a=p.parse_args();pristine()
    if a.check_pristine:print('pristine empty factory verified');return
    assert a.apply
    pins=json.loads((ROOT/'preparation/pins.json').read_text());release=json.loads((WORK/'runtime-release.json').read_text())
    release_dir=Path('/var/lib/wizard/frozen-release');release_dir.mkdir(parents=True,exist_ok=True)
    target=release_dir/(release['version']+'.json');shutil.copy2(WORK/'runtime-release.json',target);assert sha(target)==sha(WORK/'runtime-release.json')
    # Debian workaround from the primary advisory; do not use the retained stale roots to bootstrap HTTPS.
    config=Path('/etc/ca-certificates.conf')
    roots={'mozilla/emSign_ECC_Root_CA_-_G3.crt','mozilla/Comodo_AAA_Services_root.crt'}
    config.write_text('\n'.join('!'+line if line in roots else line for line in config.read_text().splitlines())+'\n')
    run(['update-ca-certificates','--fresh'])
    run(['apt-get','update'],timeout=300)
    run(['apt-get','install','-y','--no-install-recommends','ca-certificates','curl','python3-yaml'],timeout=600)
    plan=json.loads((ROOT/'preparation/security-image-plan.json').read_text());assert plan['complete'] is True
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
    run(['python3',ROOT/'preparation/guest-security-apply.py','--prepare'],timeout=1800)
    installer=ROOT/'final/wam/get.sh';assert sha(installer)==pins['osInstaller']['sha256']
    env={k:v for k,v in os.environ.items() if k not in ['WAM_REF','WAM_IMAGE','WIZARD_SHELL_IMAGE','WIZARD_UX_IMAGE','WIZARD_AGENT_SERVICE_IMAGE']}
    env.update(WIZARD_RELEASE=release['version'],WIZARD_RELEASE_BASE='file://'+str(release_dir),WIZARD_STRICT='1',WIZARD_MODE='fresh',WIZARD_PRIVATE_ACCESS='tailscale')
    for component,key in [('wizard-app-manager','WAM_IMAGE'),('wizard-ux','WIZARD_UX_IMAGE'),('wizard-agent-service','WIZARD_AGENT_SERVICE_IMAGE')]:
        item=release['images'][component];env[key]=item['ref']+'@'+item['digest']
    run(['bash',installer],env=env,stdin=subprocess.DEVNULL,timeout=3600)
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
    # Mandatory on host and EVERY running container's actual mounted trust stores, not fresh docker runs.
    run(['python3',ROOT/'preparation/security-closure.py','--guest','--output',WORK/'security-guest.json'],timeout=3600)
    pristine();(WORK/'applied.json').write_text(json.dumps({'releaseSha256':sha(target),'sources':pins['finalPins'],'pristine':True,'securityClosure':True,'publishing':False},indent=2)+'\n')

if __name__=='__main__':main()
