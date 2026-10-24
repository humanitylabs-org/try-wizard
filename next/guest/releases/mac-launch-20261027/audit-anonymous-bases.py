#!/usr/bin/env python3
"""Read-only registry manifest audit using an empty Docker auth configuration.
No layer pulls, image builds, publication or credentials. Hub bases use mirrors only.
"""
import argparse, concurrent.futures, datetime, json, subprocess
from pathlib import Path
import local_oci as oci
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',required=True,type=Path);a=p.parse_args();root=a.stage_root.resolve()
    out=root/'anonymous-base-audit';out.mkdir(exist_ok=True);env=oci.environment(out)
    plan=json.loads((HERE/'security-image-plan.json').read_text())
    def check(target):
        row={'key':target['key']}
        if target['resolution']=='selected-core-image':return {**row,'status':'local-source-build','receipt':target['receipt']}
        if target.get('baseComponent'):
            # Keep the rejected upstream visible in the audit, not in the executable plan.
            recorder=json.loads((HERE/'pins.json').read_text())['recorderImage']
            ref=recorder.get('upstreamArm64Image',recorder['arm64Image'])
        else:ref=target['base']
        row['base']=ref;records={}
        try:
            exact=oci.mirror(ref,env,records)
            proc=subprocess.run([oci.DOCKER,'buildx','imagetools','inspect',exact,'--format','{{json .Manifest}}'],env=env,capture_output=True,text=True,timeout=120,check=True)
            doc=json.loads(proc.stdout)
            assert doc['digest']==ref.split('@')[1]
            return {**row,'status':'anonymous-manifest-readable','resolved':exact,'digest':doc['digest'],'mirrors':records}
        except (subprocess.SubprocessError,AssertionError,ValueError,RuntimeError) as exc:
            return {**row,'status':'anonymous-manifest-failed','error':str(exc),'stderr':getattr(exc,'stderr',None),'localReplacement':target.get('baseComponent')}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(check,plan['targets']))
    result={'checkedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'auth':'empty inline auths, no credential store','scope':'exact manifests, not layer downloads','targets':rows}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
