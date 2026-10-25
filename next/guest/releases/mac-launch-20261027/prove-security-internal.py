#!/usr/bin/env python3
"""Thales light integration: isolated infrastructure passes, trust drift fails.
Uses already-loaded exact images and a prior successful image preflight. No builds,
pulls, external writes, release VM, network attachment changes or daemon mounts.
"""
import argparse, importlib.util, json, os, subprocess, time
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('closure',HERE/'security-closure.py');assert spec and spec.loader
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);p.add_argument('--evidence-root',required=True,type=Path);p.add_argument('--docker',default='/opt/homebrew/bin/docker');a=p.parse_args()
root=a.stage_root.resolve();out=a.evidence_root.resolve();out.mkdir(parents=True,exist_ok=False)
D=a.docker;env=os.environ.copy();net='factory-security-regression-'+str(os.getpid());results=[]

def run(*argv,**kwargs):
    return subprocess.run([D,*argv],capture_output=True,text=True,env=env,timeout=60,**kwargs)

assert run('network','create','--internal',net).returncode==0
try:
    plan=json.loads((root/'preparation/security-image-plan.json').read_text())
    for key in ['postgres','rabbitmq']:
        image=plan['resolutions'][key]['imageId']
        for mode in ['normal','trust-env-drift','blocked-root-injected']:
            name=net+'-'+key+'-'+mode
            try:
                args=['run','--pull=never','-d','--name',name,'--network',net,'--tmpfs','/tmp']
                if mode!='blocked-root-injected':args+=['--read-only']
                if mode=='trust-env-drift':args+=['-e','SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt']
                r=run(*args,'--entrypoint','/bin/sh',image,'-c','sleep 240');assert r.returncode==0,r.stderr
                row=m.inspect_container(D,name);assert m.internal_only(D,row)
                dns=run('exec',name,'curl','--max-time','5','-fsS','https://example.com/');assert dns.returncode==6,dns.stderr
                if mode=='blocked-root-injected':
                    pem=json.loads((HERE/'security-primary-evidence.json').read_text())['roots']['data'][0]['pem']
                    r=run('exec','-i',name,'python3','-c',"import sys;open('/etc/ssl/certs/ca-certificates.crt','a').write(sys.stdin.read())",input=pem);assert r.returncode==0,r.stderr
                try:
                    proof=m.check_internal(D,root,row,env)
                    assert mode=='normal','drifted running trust unexpectedly accepted'
                    result={'key':key,'mode':mode,'passed':True,'dnsReturncode':dns.returncode,'proof':proof}
                except AssertionError as exc:
                    if mode=='normal' or 'unexpectedly accepted' in str(exc):raise
                    result={'key':key,'mode':mode,'passed':True,'dnsReturncode':dns.returncode,'expectedFailure':str(exc)}
                results.append(result);print(json.dumps(result))
                (out/'result.json').write_text(json.dumps({'passed':len(results)==6,'checks':results},indent=2))
            finally:run('rm','-f',name)
finally:run('network','rm',net)
assert len(results)==6
