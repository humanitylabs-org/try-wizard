"""Disposable factory Docker migration. Keep hidden classic data; never infer it is unused."""
import json, os, subprocess
from pathlib import Path
RT=Path('/home/wizard/runtipi')
SNAPSHOTTER='io.containerd.snapshotter.v1'

def run(argv,**kw):
    return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',300),**kw)

def containers():
    ids=run(['docker','ps','-aq']).split()
    return json.loads(run(['docker','inspect',*ids])) if ids else []

def disk():
    stat=os.statvfs('/')
    sizes={}
    for name in ['overlay2','image','containers']:
        path=Path('/var/lib/docker')/name
        sizes[str(path)]=int(run(['du','-sx','-B1',path]).split()[0]) if path.exists() else 0
    return {'totalBytes':stat.f_blocks*stat.f_frsize,'usedBytes':(stat.f_blocks-stat.f_bfree)*stat.f_frsize,'availableBytes':stat.f_bavail*stat.f_frsize,'classicPathsBytes':sizes,'classicDataReclaimed':False,'reason':'Hidden classic containers/layers retained; do not delete or switch back.'}

def assert_store():
    info=json.loads(run(['docker','info','-f','{{json .}}']))
    assert ['driver-type',SNAPSHOTTER] in info.get('DriverStatus',[]),'containerd snapshotter not active: '+repr(info.get('DriverStatus'))
    return {k:info[k] for k in ['Driver','DriverStatus','DockerRootDir']}

def enable(work,config=Path('/etc/docker/daemon.json')):
    assert os.geteuid()==0 and not Path('/var/lib/wizard/setup.json').exists()
    snapshot=work/'docker-store-before.json';assert not snapshot.exists(),'store migration must start once on a fresh clone'
    rows=containers();assert rows,'retained factory containers missing before migration'
    # Preserve image IDs/labels/digests before Docker hides the entire classic namespace.
    for row in rows:row['FactoryImage']=json.loads(run(['docker','image','inspect',row['Image']]))[0]
    snapshot.write_text(json.dumps(rows,indent=2)+'\n');snapshot.chmod(0o600)
    receipt={'before':disk(),'inheritedContainers':len(rows)}
    doc=json.loads(config.read_text()) if config.exists() else {}
    assert isinstance(doc,dict) and isinstance(doc.get('features',{}),dict)
    doc.setdefault('features',{})['containerd-snapshotter']=True
    config.parent.mkdir(parents=True,exist_ok=True)
    temporary=config.with_name(config.name+'.launch-new');temporary.write_text(json.dumps(doc,indent=2)+'\n');temporary.chmod(0o644);os.replace(temporary,config)
    run(['systemctl','restart','docker'],timeout=120)
    receipt.update(store=assert_store(),afterSwitch=disk())
    (work/'docker-store.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return rows

def inherited(work):
    return json.loads((work/'docker-store-before.json').read_text())

def host_path(value):
    # App-manager compose labels use container paths; verification executes on the guest host.
    for prefix,target in [('/app-data',str(RT/'app-data')),('/data',str(RT))]:
        if value==prefix or value.startswith(prefix+'/'):return target+value[len(prefix):]
    return value

def compose_projects(rows):
    projects={}
    for c in rows:
        labels=c['Config'].get('Labels') or {};name=labels.get('com.docker.compose.project')
        if not name:continue  # Non-compose containers still have both ref and ID checked below.
        files=tuple(host_path(x) for x in labels['com.docker.compose.project.config_files'].split(','))
        wd=host_path(labels['com.docker.compose.project.working_dir'])
        app_root=RT/'apps/wizardapps'
        if Path(wd).parent==app_root:
            override=str(RT/'user-config/wizardapps'/Path(wd).name/'docker-compose.yml')
            if Path(override).is_file() and override not in files:files=(*files,override)
        key=(name,files,wd)
        project=projects.setdefault(key,{'name':name,'files':files,'directory':wd,'env':set()})
        project['env'].update(host_path(x) for x in labels.get('com.docker.compose.project.environment_file','').split(',') if x)
    return list(projects.values())

def compose_argv(project):
    argv=['docker','compose','--project-name',project['name'],'--project-directory',project['directory']]
    for path in sorted(project['env']):argv+=['--env-file',path]
    for path in project['files']:argv+=['-f',path]
    return argv

def bootstrap(work):
    """Bring up selected manager/DB/queue/proxy before the strict installer needs its API."""
    projects=[p for p in compose_projects(inherited(work)) if p['name']=='runtipi'];assert len(projects)==1
    run([*compose_argv(projects[0]),'up','-d','--pull','never','--force-recreate'],timeout=600)

def verify(work,rows=None,receipt='docker-image-resolution.json'):
    """Resolve effective compose and every container's ref/ID, including stopped containers."""
    assert_store();current=containers();assert current,'no recreated factory containers'
    refs={};errors=[]
    projects=compose_projects(current+(rows or []))
    for p in projects:
        for ref in run([*compose_argv(p),'config','--images'],cwd=p['directory']).split():refs.setdefault(ref,set()).add('compose:'+p['name'])
    for c in current:
        for ref in [c['Config']['Image'],c['Image']]:refs.setdefault(ref,set()).add('container:'+c['Name'])
    resolved={}
    for ref,origins in sorted(refs.items()):
        try:
            image=json.loads(run(['docker','image','inspect',ref],stderr=subprocess.PIPE))[0]
            assert image['Architecture']=='arm64'
            if '@sha256:' in ref:assert ref in image.get('RepoDigests',[]),'digest not preserved'
            resolved[ref]={'imageId':image['Id'],'origins':sorted(origins)}
        except (subprocess.SubprocessError,ValueError,IndexError,AssertionError) as exc:errors.append({'ref':ref,'origins':sorted(origins),'error':str(exc)})
    for c in current:
        selected=resolved.get(c['Config']['Image'])
        if selected and selected['imageId']!=c['Image']:errors.append({'ref':c['Config']['Image'],'container':c['Name'],'error':'container ID differs from recreatable image'})
        if c.get('GraphDriver',{}).get('Name')=='overlay2':errors.append({'container':c['Name'],'error':'classic container retained in active store'})
    result={'store':assert_store(),'resolved':resolved,'unresolved':errors,'containers':len(current),'projects':len(projects),'disk':disk(),'pullsAllowed':False}
    (work/receipt).write_text(json.dumps(result,indent=2)+'\n')
    assert not errors,'unresolved image refs: '+json.dumps(errors)
    return result
