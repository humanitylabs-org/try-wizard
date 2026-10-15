#!/usr/bin/env python3
"""Run both unchanged stock dispatcher branches with the managed image."""
import argparse,hashlib,json,subprocess as sp,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
image=json.loads(Path('/opt/wizard/managed-runtime.json').read_text())['image'];receipts=[]
stock='sha256:666d6c659574fa09c1ea47b7ec5f03e8d2c35a8aa8055fe60c1e2fe3d3e03e9b'
path='/opt/hermes/docker/entrypoint-dispatch.sh'
blobs=[sp.check_output(['docker','run','--rm','--network','none','--entrypoint','cat',i,path]) for i in [stock,image]]
assert blobs[0]==blobs[1]
for init in [False,True]:
 name='managed-final-dispatch-'+uuid.uuid4().hex[:10]
 argv=['docker','run','--name',name,'--network','none','-v','/var/lib/wizard/managed:/wizard-managed-state']
 if init:argv+=['--init']
 argv += [image,'sh','-c','printf "DISPATCH_OK:"; cat /proc/1/comm']
 try:
  result=sp.run(argv,capture_output=True,text=True,timeout=120)
  assert result.returncode==0,{'init':init,'exit':result.returncode,'stderrBytes':len(result.stderr)}
  expected='docker-init' if init else 's6-svscan'
  assert 'DISPATCH_OK:'+expected in result.stdout,{'init':init,'markerFound':False}
  receipts.append({'dockerInit':init,'exit':result.returncode,'pid1':expected,'passed':True})
 finally:sp.run(['docker','rm','-f',name],capture_output=True,check=True)
a.output.write_text(json.dumps({'stockDispatcherBytesEqual':True,'sha256':hashlib.sha256(blobs[0]).hexdigest(),'routes':receipts},indent=2)+'\n')
print('normal and --init stock dispatcher PASS')
