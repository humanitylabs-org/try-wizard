#!/usr/bin/env python3
"""Parent-only image derivation; no VM, source mutation, mutable tag or release publication.
Every output is pull-read-back by digest. A failed build/probe never emits a success receipt.
"""
import argparse, hashlib, importlib.util, json, os, re, shutil, subprocess, sys, urllib.request
import local_oci as oci
from pathlib import Path
HERE=Path(__file__).resolve().parent
DOCKER='/opt/homebrew/bin/docker'

def run(argv,**kw):return subprocess.check_output(list(map(str,argv)),text=True,timeout=kw.pop('timeout',120),**kw).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def wheel(context,plan):
    for key,name in [('certifi','certifi.whl'),('pip','pip.whl')]:
        item=plan['upstreamInputs'][key];p=context/name
        p.write_bytes(urllib.request.urlopen(item['url'],timeout=60).read());assert sha(p)==item['sha256']

def recipe(base,config,inventory,plan):
    user=config.get('User') or '0';assert re.fullmatch(r'[a-zA-Z0-9_:-]+',user)
    lines=[]
    if inventory.get('minimal'):
        # The retained Files engine is BusyBox/static Go, not an apt/apk distribution.
        # Keep its application/rootfs identity, transplant only the already-built fixed helper toolchain,
        # then scrub ALL original stores as well. Never pretend an absent package manager was upgraded.
        assert re.search(r'(?:^|/)filebrowser/filebrowser(?::[^@]+)?@sha256:',base)
        assert re.fullmatch(r'.+@sha256:[0-9a-f]{64}',plan['_helperImage'])
        return '\n'.join(['FROM '+plan['_helperImage']+' AS security_tools','FROM '+base,'USER 0',
            'COPY --from=security_tools /usr/local/ /usr/local/',
            'COPY --from=security_tools /usr/lib/ /usr/lib/',
            'COPY --from=security_tools /lib/ /lib/',
            'COPY --from=security_tools /usr/bin/python3* /usr/bin/',
            'COPY --from=security_tools /usr/bin/curl /usr/bin/openssl /usr/bin/',
            'COPY --from=security_tools /etc/ssl/ /etc/ssl/',
            'COPY --from=security_tools /usr/share/ca-certificates/ /usr/share/ca-certificates/',
            'COPY certifi.whl pip.whl remediate-trust.py /opt/wizard-security/',
            'RUN python3 /opt/wizard-security/remediate-trust.py --wheel /opt/wizard-security/certifi.whl --pip-wheel /opt/wizard-security/pip.whl --output /opt/wizard-security/remediation.json && rm /opt/wizard-security/certifi.whl /opt/wizard-security/pip.whl',
            'USER '+user])+'\n'
    major=inventory['nodeMajor'];alpine=inventory['alpine']
    if major:
        assert major in [22,24,26], 'unknown Node major must be reviewed'
        node=plan['upstreamInputs']['node'+str(major)+('-alpine' if alpine else '-glibc')]['image']
        lines+=['FROM '+node+' AS fixed_node']
    lines+=['FROM '+plan['upstreamInputs']['uv']['image']+' AS fixed_uv','FROM '+base,'USER 0']
    lines+=['RUN '+('apk add --no-cache --upgrade ca-certificates curl python3 openssl' if alpine else 'apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3 openssl && rm -rf /var/lib/apt/lists/*')]
    if major:
        lines+=['COPY --from=fixed_node /usr/local/bin/node /opt/wizard-security/node',
                'RUN target=$(readlink -f "$(command -v node)") && cp /opt/wizard-security/node "$target" && rm /opt/wizard-security/node && node --version']
    lines+=['COPY --from=fixed_uv /uv /usr/local/bin/uv','COPY --from=fixed_uv /uvx /usr/local/bin/uvx','COPY certifi.whl pip.whl remediate-trust.py /opt/wizard-security/']
    lines+=['RUN python3 /opt/wizard-security/remediate-trust.py --wheel /opt/wizard-security/certifi.whl --pip-wheel /opt/wizard-security/pip.whl --output /opt/wizard-security/remediation.json']
    # Claude's native executable carries an independent runtime; OS/certifi upgrades cannot repair it.
    if inventory['claude']:
        assert major, 'Claude Code upgrade requires Node/npm'
        lines+=['RUN npm install --global @anthropic-ai/claude-code@2.1.303 && claude --version','ENV CLAUDE_CODE_VERSION=2.1.303']
    lines+=['RUN rm /opt/wizard-security/certifi.whl /opt/wizard-security/pip.whl','USER '+user]
    return '\n'.join(lines)+'\n'

INVENTORY=r'''set -eu
python_cmd="$(command -v python3 || true)"
if command -v node >/dev/null; then major=$(node -p 'process.versions.node.split(".")[0]'); else major=0; fi
minimal=false
if test -f /etc/alpine-release; then alpine=true; elif test -f /etc/debian_version || test -f /etc/lsb-release; then alpine=false; else alpine=false; minimal=true; fi
if command -v claude >/dev/null; then claude=true; else claude=false; fi
printf '{"nodeMajor":%s,"alpine":%s,"claude":%s,"minimal":%s}\n' "$major" "$alpine" "$claude" "$minimal"
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage-root',type=Path,required=True);p.add_argument('--target',required=True);a=p.parse_args()
    root=a.stage_root.resolve();assert sys.platform=='darwin' and root.is_relative_to(Path(os.environ['THALES_MEDIA']))
    plan=json.loads((HERE/'security-image-plan.json').read_text());target=next(t for t in plan['targets'] if t['key']==a.target)
    assert target['resolution']=='derive-image'
    base=target['base'];assert re.fullmatch(r'.+@sha256:[0-9a-f]{64}',base)
    out=root/'security-packaging'/a.target
    if (out/'result.json').exists():
        row=json.loads((out/'result.json').read_text());assert row['base']==base and row['key']==a.target and row['recipeSha256']==sha(out/'recipe.json')
        oci.load(root,row,DOCKER,oci.environment(out));print(json.dumps({**row,'reusedVerifiedArchive':True}));return
    out.mkdir(exist_ok=False,parents=True);context=out/'context';context.mkdir()
    env=oci.environment(out);mirrors={}
    base=oci.mirror(base,env,mirrors)
    run([DOCKER,'pull','--platform','linux/arm64',base],env=env,timeout=300)
    obj=json.loads(run([DOCKER,'inspect',base],env=env))[0];assert obj['Architecture']=='arm64'
    raw=subprocess.run([DOCKER,'run','--rm','-i','--read-only','--cap-drop=ALL','--entrypoint','/bin/sh',base,'-s'],input=INVENTORY,capture_output=True,text=True,env=env,timeout=60,check=True)
    inventory=json.loads(raw.stdout);emit(out/'base-inventory.json',inventory)
    if inventory.get('minimal'):
        helper=json.loads((root/'security-packaging/helper-python/result.json').read_text())
        expected=next(t['base'] for t in plan['targets'] if t['key']=='helper-python')
        assert helper['base']==expected and helper['loadVerified'] is True and helper['tagsPublished'] is False
        oci.validate(root,helper)
        plan['_helperImage']=helper['ref']+'@'+helper['digest']
    wheel(context,plan);shutil.copy2(HERE/'remediate-trust.py',context/'remediate-trust.py')
    text=recipe(base,obj['Config'],inventory,plan)
    for match in list(re.finditer(r'^FROM (\S+)',text,re.M)):
        ref=match.group(1);text=text.replace(ref,oci.mirror(ref,env,mirrors))
    (context/'Dockerfile').write_text(text);emit(out/'recipe.json',{'base':target['base'],'resolvedBase':base,'mirrors':mirrors,'dockerfileSha256':sha(context/'Dockerfile'),'inventory':inventory,'upstreamInputs':plan['upstreamInputs']})
    image='ghcr.io/humanitylabs-org/wizard-mac-security-'+a.target
    transport,built=oci.export(out,context,image,env)
    exact=image+'@'+transport['digest']
    # Preserve runtime identity/entrypoint/cmd and source labels, not just filesystem bytes.
    for field in ['User','Entrypoint','Cmd','WorkingDir','Labels','Volumes']:
        actual=built['Config'].get(field) or ('0' if field=='User' else None)
        expected=obj['Config'].get(field) or ('0' if field=='User' else None)
        assert actual==expected,field
    with oci.probe_mount([HERE/'security-probe.py'],exact,env) as mount:
        remediation=json.loads(run([DOCKER,'run','--pull=never','--rm','--entrypoint','/bin/sh','-v',mount,exact,'-lc','PY=$(command -v python3 || command -v python); "$PY" /opt/wizard-probe/security-probe.py'],env=env,timeout=300).splitlines()[-1])
    result={**transport,'key':a.target,'base':target['base'],'archive':str(Path(transport['archive']).relative_to(root)),'recipeSha256':sha(out/'recipe.json'),'remediation':remediation}
    emit(out/'result.json',result);print(json.dumps(result))

if __name__=='__main__':main()
