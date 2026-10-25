#!/usr/bin/env python3
"""Only pristine disposable factory: persist selected images, then verify final writers.
Does not touch owner/live VMs. Source recipes remain pinned and unmodified.
"""
import argparse, json, os, subprocess
from pathlib import Path
import guest_docker_store as store
ROOT=Path('/mnt/launch');PREP=ROOT/'preparation';RT=Path('/home/wizard/runtipi')

def run(argv,**kw):return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',300),**kw)
def load():
    plan=json.loads((PREP/'security-image-plan.json').read_text());assert plan['complete'] is True
    assert not Path('/var/lib/wizard/setup.json').exists(),'onboarded guest refused'
    assert not list(Path('/home/wizard/runtipi/app-data/wizard-os/agents').glob('*/agent.json'))
    return plan

def merge(path,updates):
    import yaml
    # Same tagged-node preservation contract as WAM release_pins.configure_manager.
    class Tagged:
        def __init__(self,tag,value):self.tag,self.value=tag,value
    class Loader(yaml.SafeLoader):pass
    class Dumper(yaml.SafeDumper):pass
    def tagged(loader,tag,node):
        make={yaml.ScalarNode:loader.construct_scalar,yaml.SequenceNode:loader.construct_sequence,yaml.MappingNode:loader.construct_mapping}[type(node)]
        return Tagged('!'+tag,make(node))
    def represent(dumper,value):
        node=dumper.represent_data(value.value);node.tag=value.tag;return node
    Loader.add_multi_constructor('!',tagged);Dumper.add_representer(Tagged,represent)
    # Preserve WAM's generated quoted loopback listen while merging image pins.
    def represent_string(dumper,value):
        return dumper.represent_scalar('tag:yaml.org,2002:str',value,style='"' if value.startswith('127.0.0.1:') else None)
    Dumper.add_representer(str,represent_string)
    assert not path.is_symlink()
    doc=yaml.load(path.read_text(),Loader=Loader) if path.exists() else {};doc=doc or {}
    for service,image in updates.items():doc.setdefault('services',{}).setdefault(service,{}).update(image=image,pull_policy='if_not_present')
    owned = path.parent.name in {'hermes-agent','wizard-ux','wizard-agent-service'}
    if owned and path.exists():assert path.read_text().startswith('# Written by wam'), 'foreign fresh overlay refused'
    marker = '# Written by wam (fresh mode): factory-selected immutable image bindings' if owned else ''
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text((marker+'\n' if marker else '')+yaml.dump(doc,Dumper=Dumper,sort_keys=False));os.chown(path.parent,1000,1000);os.chown(path,1000,1000)
    read=yaml.load(path.read_text(),Loader=Loader)
    assert all(read['services'][s]['image']==v for s,v in updates.items())
    return {'path':str(path),'images':updates}

def prepare(plan,managed=None):
    bindings=json.loads((PREP/'security-compose-bindings.json').read_text())['bindings'];byapp={}
    for b in bindings:
        image=plan['resolutions'][b['target']]['image']
        if managed and b['service']=='hermes-agent-engine':image=managed
        byapp.setdefault(b['app'],{})[b['service']]=image
    # The combined shell is retired through the lifecycle API, never rebound to a UX-only image.
    assert (ROOT/'assembly-work/factory-overlays.json').is_file(), 'factory migration gate missing'
    assert 'wizard-shell' not in byapp, 'legacy shell unexpectedly selected'
    writes=[merge(RT/'user-config/wizardapps'/app/'docker-compose.yml',updates) for app,updates in byapp.items()]
    # Read service names from actual retained compose labels, matched by immutable image ID.
    containers=store.containers() or store.inherited(ROOT/'assembly-work');infra={}
    for target in plan['targets']:
        if target['key'] not in {'postgres','rabbitmq','traefik'}:continue
        # The classic store is now hidden. Its captured RepoDigests, not tag guesses,
        # identify the retained infrastructure service for the first bootstrap.
        old_ids={c['Image'] for c in store.inherited(ROOT/'assembly-work') if target['base'] in c['FactoryImage'].get('RepoDigests',[])}
        patched=json.loads(run(['docker','image','inspect',plan['resolutions'][target['key']]['image']]))[0]
        hits=[c for c in containers if c['Image'] in old_ids|{patched['Id']}]
        assert len(hits)==1,(target['key'],len(hits))
        service=hits[0]['Config']['Labels']['com.docker.compose.service'];infra[service]=plan['resolutions'][target['key']]['image']
    manager=[c for c in store.inherited(ROOT/'assembly-work') if (c['Config'].get('Labels') or {}).get('com.docker.compose.service')=='runtipi']
    assert len(manager)==1,'retained manager service missing/ambiguous'
    infra['runtipi']=plan['resolutions']['wam']['image']
    writes.append(merge(RT/'user-config/tipi-compose.yml',infra))
    return writes

def finish(plan):
    managed=json.loads(Path('/opt/wizard/managed-runtime.json').read_text())['image']
    writes=prepare(plan,managed)
    bindings=json.loads((PREP/'security-compose-bindings.json').read_text())['bindings']
    before=json.loads(run(['docker','inspect',*run(['docker','ps','-q']).split()]))
    running_services={c['Config'].get('Labels',{}).get('com.docker.compose.service') for c in before}
    assert 'wizard-shell' not in running_services, 'retired combined shell still running'
    apps={b['app'] for b in bindings if b['service'] in running_services}
    for app in sorted(apps):
        run(['sudo','-iu','wizard','wam','app','restart',app],timeout=900)
    current=json.loads(run(['docker','inspect',*run(['docker','ps','-q']).split()]))
    expected={key:json.loads(run(['docker','image','inspect',value['image']]))[0]['Id'] for key,value in plan['resolutions'].items()}
    expected['managed']=managed
    for b in bindings:
        hits=[c for c in current if (c['Config'].get('Labels') or {}).get('com.docker.compose.service')==b['service']]
        if not hits:continue  # Uninstalled optional app is not a runtime exemption: 05 still checked its selected image.
        want=managed if b['service']=='hermes-agent-engine' else expected[b['target']]
        assert all(c['Image']==want for c in hits),'default image drift: '+b['service']
    assert all(c['Image'] in set(expected.values()) for c in current),'unplanned running image'
    # Remove obsolete local-image families rather than inventing upstream digests for them.
    stopped=run(['docker','ps','-aq','--filter','status=exited']).split()
    if stopped:run(['docker','rm',*stopped])
    # Keep every selected OCI image: optional/stopped compose services must remain recreatable offline.
    retained_before=set(run(['docker','image','ls','-q','--no-trunc']).split())
    for image in sorted(retained_before-set(expected.values())):run(['docker','image','rm',image])
    run(['docker','builder','prune','-a','-f'],timeout=300)
    retained=run(['docker','image','ls','-q','--no-trunc']).split()
    assert set(retained)<=set(expected.values()),'unplanned inherited/cached image retained'
    assert set(expected.values())<=set(retained),'selected OCI image missing after cleanup'
    receipt={'writes':writes,'running':[{'name':c['Name'],'image':c['Image']} for c in current],'retainedImageIds':sorted(set(retained)),'expectedImageIds':expected,'oldLocalImagesRemoved':True,'cleanupScope':'active containerd store only','classicStore':store.disk()}
    (ROOT/'assembly-work/security-application.json').write_text(json.dumps(receipt,indent=2)+'\n')

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--finish',action='store_true');a=p.parse_args();assert os.geteuid()==0;plan=load()
    # Images were imported from byte-verified OCI archives before the installer. Never pull.
    for row in plan['resolutions'].values():run(['docker','image','inspect',row['image']])
    if a.prepare:print(json.dumps(prepare(plan),indent=2))
    else:finish(plan)

if __name__=='__main__':main()
