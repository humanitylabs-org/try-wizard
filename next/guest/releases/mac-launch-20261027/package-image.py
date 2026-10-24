#!/usr/bin/env python3
"""Exact source to a verified local OCI archive, no registry publication or login."""
import argparse, hashlib, json, os, re, shutil, subprocess, sys
import local_oci as oci
from pathlib import Path

DOCKER='/opt/homebrew/bin/docker'
HERE=Path(__file__).resolve().parent

def run(argv, **kw):
    return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',120),**kw).strip()

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage-root',required=True,type=Path)
    p.add_argument('--component',choices=['wam','service','ux','recorder'],required=True)
    a=p.parse_args();root=a.stage_root.resolve();pins=json.loads((HERE/'pins.json').read_text())
    if sys.platform!='darwin' or not root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media'))):p.error('ThalesMedia only')
    key=a.component;source=root/('inputs' if key=='recorder' else 'final')/key;commit=pins['finalPins'][key]
    assert json.loads((source/'.wizard-source.json').read_text())['commit']==commit
    image='ghcr.io/humanitylabs-org/'+{'wam':'wizard-app-manager','service':'wizard-agent-service','ux':'wizard-ux','recorder':'wizard-recorder'}[key]
    out=root/'image-packaging'/key
    if (out/'result.json').exists():
        row=json.loads((out/'result.json').read_text());assert row['sourceCommit']==commit and row['ref']==image and row['recipeSha256']==sha(out/'recipe.json')
        oci.load(root,row,DOCKER,oci.environment(out));print(json.dumps({**row,'reusedVerifiedArchive':True}));return
    out.mkdir(exist_ok=False,parents=True)
    env=oci.environment(out)
    # Resolve each external FROM before the Docker build; keep exact resolution and rendered recipe.
    context=out/'context';shutil.copytree(source,context,symlinks=True)
    # Recorder's Dockerfile is app/Dockerfile but COPY paths are repository-relative.
    if key=='recorder':shutil.copy2(context/'app/Dockerfile',context/'Dockerfile')
    text=(context/'Dockerfile').read_text();mirror_records={};args=dict(re.findall(r'^ARG (\w+)="([^"]+)"',text,re.M));bases={}
    if key=='wam':args.update(NODE_VERSION='22',BUN_VERSION='1.4.4')  # primary advisory patched builder/runtime
    for match in list(re.finditer(r'^FROM (?:--platform=\S+ )?(\S+)',text,re.M)):
        ref=match.group(1)
        for k,v in args.items():ref=ref.replace('${'+k+'}',v)
        if '/' not in ref and ':' not in ref:continue  # named prior stage
        if key=='wam' and ref.startswith('node:'):ref='node:22.23.4-alpine'  # 22.23.4 = security floor; alpine3.21 tags stopped earlier
        if key=='recorder' and ref.startswith('node:'):ref='node:22.23.4-bookworm-slim'
        bases[ref]=oci.mirror(ref,env,mirror_records)
        text=text.replace(match.group(1),bases[ref])
    trust=('apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && update-ca-certificates && rm -rf /var/lib/apt/lists/*' if key=='recorder' else 'apk add --no-cache --upgrade ca-certificates curl && update-ca-certificates')
    text=re.sub(r'^(FROM (?:--platform=\S+ )?\S+@sha256:[0-9a-f]{64}(?: AS \w+)?\n)',lambda m:m[0]+'RUN '+trust+'\n',text,flags=re.M)
    # Preserve each app's runtime user and distribution; Node must carry the fixed runtime.
    user='101:101' if key=='ux' else ('1000:1000' if key in ('service','recorder') else '0')
    text+='\nUSER 0\nRUN '+trust+'\n'
    text+='RUN curl -fsS --max-time 30 https://example.com/ >/dev/null && for h in dv-g3b-emudhra dv-g3b-aaa-emudhra; do rc=0; curl -fsS --max-time 30 https://$h.we-have-a-problem.com/ >/dev/null || rc=$?; test "$rc" = 60 || exit 1; done\n'
    if key in ('wam','service','recorder'):
        text+='RUN node -e "let v=process.versions.node.split(\'.\').map(Number); if(v[0]<22 || (v[0]===22 && (v[1]<23 || (v[1]===23 && v[2]<4)))) process.exit(1)"\n'
        text+='RUN node -e "const h=require(\'https\'); let r=h.get(\'https://dv-g3b-emudhra.we-have-a-problem.com/\',()=>process.exit(1)); r.setTimeout(30000,()=>process.exit(2)); r.on(\'error\',e=>{if(!/CERT|ISSUER|VERIFY|SELF_SIGNED/.test(e.code||\'\'))process.exit(2)})"\n'
    text+='USER '+user+'\n'
    (context/'Dockerfile').write_text(text)
    (out/'recipe.json').write_text(json.dumps({'source':commit,'fromImages':bases,'mirrors':mirror_records,'dockerfileSha256':sha(context/'Dockerfile')},indent=2)+'\n')
    extra=['--label','org.opencontainers.image.revision='+commit]
    if key=='wam':extra+=['--build-arg','LOCAL=true','--build-arg','NODE_VERSION=22','--build-arg','BUN_VERSION=1.4.4','--build-arg','TIPI_VERSION=mac-launch-'+commit[:12]]
    result,obj=oci.export(out,context,image,env,extra)
    assert obj['Config']['Labels']['org.opencontainers.image.revision']==commit
    result.update(component=key,sourceCommit=commit,archive=str(Path(result['archive']).relative_to(root)),recipeSha256=sha(out/'recipe.json'))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
