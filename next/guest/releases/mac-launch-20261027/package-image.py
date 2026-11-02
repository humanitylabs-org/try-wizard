#!/usr/bin/env python3
"""Parent-only light Thales packaging: exact source -> GHCR digest, NO tags/feed/release.
Uses an ephemeral Docker auth directory; never accesses the macOS keychain.
Receipts are not synthesized when a build/push/test fails.
"""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile
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
    p.add_argument('--component',choices=['wam','service','ux'],required=True)
    a=p.parse_args();root=a.stage_root.resolve();pins=json.loads((HERE/'pins.json').read_text())
    if sys.platform!='darwin' or not root.is_relative_to(Path(os.environ.get('THALES_MEDIA','/unconfigured-external-media'))):p.error('ThalesMedia only')
    key=a.component;source=root/'final'/key;commit=pins['finalPins'][key]
    assert json.loads((source/'.wizard-source.json').read_text())['commit']==commit
    out=root/'image-packaging'/key;out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,'PATH':'/opt/homebrew/bin:'+os.environ.get('PATH',''),'TMPDIR':str(out)}
    # Resolve each external FROM before the Docker build; keep exact resolution and rendered recipe.
    context=out/'context';shutil.copytree(source,context,symlinks=True)
    text=(context/'Dockerfile').read_text();args=dict(re.findall(r'^ARG (\w+)="([^"]+)"',text,re.M));bases={}
    if key=='wam':args.update(NODE_VERSION='22',BUN_VERSION='1.4.4')  # primary advisory patched builder/runtime
    for match in list(re.finditer(r'^FROM (?:--platform=\S+ )?(\S+)',text,re.M)):
        ref=match.group(1)
        for k,v in args.items():ref=ref.replace('${'+k+'}',v)
        if '/' not in ref and ':' not in ref:continue  # named prior stage
        obj=json.loads(run([DOCKER,'buildx','imagetools','inspect',ref,'--format','{{json .Manifest}}'],env=env))
        digest=obj['digest'];assert re.fullmatch('sha256:[0-9a-f]{64}',digest)
        repo=re.sub(r'(@.*|:[^/:]*)$','',ref);bases[ref]=repo+'@'+digest
        text=text.replace(match.group(1),bases[ref])
    text=re.sub(r'^(FROM (?:--platform=\S+ )?\S+@sha256:[0-9a-f]{64}(?: AS \w+)?\n)',r'\1RUN apk add --no-cache --upgrade ca-certificates && update-ca-certificates\n',text,flags=re.M)
    # All three outputs receive the patched Alpine trust package. Node images must carry the fixed runtime.
    user='101:101' if key=='ux' else ('1000:1000' if key=='service' else '0')
    text+='\nUSER 0\nRUN apk add --no-cache --upgrade ca-certificates curl && update-ca-certificates && apk info -v ca-certificates\n'
    text+='RUN curl -fsS --max-time 30 https://example.com/ >/dev/null && for h in dv-g3b-emudhra dv-g3b-aaa-emudhra; do rc=0; curl -fsS --max-time 30 https://$h.we-have-a-problem.com/ >/dev/null || rc=$?; test "$rc" = 60 || exit 1; done\n'
    if key in ('wam','service'):
        text+='RUN node -e "let v=process.versions.node.split(\'.\').map(Number); if(v[0]<22 || (v[0]===22 && (v[1]<23 || (v[1]===23 && v[2]<4)))) process.exit(1)"\n'
        text+='RUN node -e "const h=require(\'https\'); let r=h.get(\'https://dv-g3b-emudhra.we-have-a-problem.com/\',()=>process.exit(1)); r.setTimeout(30000,()=>process.exit(2)); r.on(\'error\',e=>{if(!/CERT|ISSUER|VERIFY|SELF_SIGNED/.test(e.code||\'\'))process.exit(2)})"\n'
    text+='USER '+user+'\n'
    (context/'Dockerfile').write_text(text)
    (out/'recipe.json').write_text(json.dumps({'source':commit,'fromImages':bases,'dockerfileSha256':sha(context/'Dockerfile')},indent=2)+'\n')
    image='ghcr.io/humanitylabs-org/'+{'wam':'wizard-app-manager','service':'wizard-agent-service','ux':'wizard-ux'}[key]
    # Existing authenticated gh account only. Token remains in this process and private config, never stdout.
    # Missing packages:write fails the real push; do not claim a digest is pullable from build metadata alone.
    with tempfile.TemporaryDirectory(prefix='auth-',dir=out) as td:
        os.chmod(td,0o700);auth=Path(td)
        token=run(['gh','auth','token'],env=env);user=run(['gh','api','user','--jq','.login'],env=env)
        cfg=auth/'config.json';cfg.write_text(json.dumps({'auths':{'ghcr.io':{'auth':base64.b64encode((user+':'+token).encode()).decode()}}}));cfg.chmod(0o600)
        env['DOCKER_CONFIG']=td
        # Keep the existing daemon endpoint without copying any keychain-backed Docker configuration.
        if not env.get('DOCKER_HOST'):
            context_name=run([DOCKER,'context','show'])
            env['DOCKER_HOST']=json.loads(run([DOCKER,'context','inspect',context_name]))[0]['Endpoints']['docker']['Host']
        # Config isolation hides CLI plugins: invoke the existing buildx binary explicitly through its normal CLI
        # plugin directory symlink (no credentials copied).
        plugins=auth/'cli-plugins';plugins.mkdir()
        candidates=[Path('/opt/homebrew/lib/docker/cli-plugins/docker-buildx'),Path.home()/'.docker/cli-plugins/docker-buildx']
        plugin=next((x for x in candidates if x.exists()),None)
        if plugin:(plugins/'docker-buildx').symlink_to(plugin.resolve())
        argv=[DOCKER,'buildx','build','--platform','linux/arm64','--provenance=false','--label','org.opencontainers.image.revision='+commit,
              '--metadata-file',str(out/'metadata.json'),'--output','type=image,name='+image+',push-by-digest=true,name-canonical=true,push=true']
        if key=='wam':argv+=['--build-arg','LOCAL=true','--build-arg','NODE_VERSION=22','--build-arg','BUN_VERSION=1.4.4','--build-arg','TIPI_VERSION=mac-launch-'+commit[:12]]
        # WAM's original node:jod-alpine is resolved too, but fixed Node 22 is separately resolved and replaces it.
        if key=='wam':
            node=json.loads(run([DOCKER,'buildx','imagetools','inspect','node:22-alpine3.21','--format','{{json .Manifest}}'],env=env))
            text=text.replace(bases.get('node:jod-alpine3.21','node:jod-alpine3.21'),'node@'+node['digest']);(context/'Dockerfile').write_text(text)
            recipe=json.loads((out/'recipe.json').read_text());recipe['fromImages']['node:22-alpine3.21']='node@'+node['digest'];recipe['dockerfileSha256']=sha(context/'Dockerfile');(out/'recipe.json').write_text(json.dumps(recipe,indent=2)+'\n')
        with (out/'build.log').open('w') as log:
            subprocess.run(argv+[str(context)],env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=780)
        digest=json.loads((out/'metadata.json').read_text())['containerimage.digest'];assert re.fullmatch('sha256:[0-9a-f]{64}',digest)
        exact=image+'@'+digest
        manifest=json.loads(run([DOCKER,'buildx','imagetools','inspect',exact,'--format','{{json .Manifest}}'],env=env))
        assert manifest['digest']==digest
        # Read back actual pulled bytes and source label, not only the exporter acknowledgement.
        run([DOCKER,'pull','--platform','linux/arm64',exact],env=env,timeout=90)
        obj=json.loads(run([DOCKER,'image','inspect',exact],env=env))[0]
        assert obj['Architecture']=='arm64' and obj['Config']['Labels']['org.opencontainers.image.revision']==commit
        result={'component':key,'sourceCommit':commit,'ref':image,'digest':digest,'imageId':obj['Id'],'pullVerified':True,'tagsPublished':False,'releasePublished':False,'recipeSha256':sha(out/'recipe.json')}
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
