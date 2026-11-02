#!/usr/bin/env python3
"""Map the frozen 84-row queue to selected commits; never mark acceptance passed.
Run on the control plane: --repos contains native/service/wam/ux git checkouts.
Ancestry is source evidence, not runtime or product acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
# Required core components identified from each original row. External/private
# apps are not silently treated as shipped by having a shell link to them.
CORE = {
 1:'ux',2:'wam',3:'native wam',4:'native service',5:'ux',6:'ux',7:'ux',8:'ux',
 10:'ux',11:'native wam',12:'ux',13:'ux',15:'ux',16:'ux',18:'ux',19:'ux',20:'ux',
 22:'ux',23:'ux',24:'service',25:'ux',26:'ux',27:'ux',28:'ux service',30:'ux',
 33:'ux',34:'ux',35:'ux',37:'ux',38:'ux',39:'ux',43:'ux',44:'ux',45:'ux service',
 46:'ux',47:'ux',48:'ux',49:'ux',50:'ux',51:'ux',52:'ux',53:'ux',55:'ux',56:'ux',
 57:'ux',58:'native wam service',59:'ux',60:'ux',61:'ux',62:'service ux',63:'ux',
 64:'ux',65:'ux',66:'ux',67:'ux native',68:'ux',69:'ux',70:'service',71:'service',
 72:'ux',73:'ux service',74:'native wam',76:'ux',77:'ux',78:'ux',79:'native',
 80:'service',82:'native',83:'service',84:'ux'}
# These rows require recipes/assets not selected by the launch manifest. Keep
# them visible even when their shell-facing half is carried.
EXTERNAL = {
 9:'Claude/ChatGPT Appearance 0.2.1 and Connection Router 0.1.1: stable defaults still select older connector recipes; router not selected',
 14:'Wisdom private release is not in frozen default_apps/sourceInputs',
 15:'Wisdom reader half is not in frozen default_apps/sourceInputs',
 17:'Wisdom epigraph overlay is not in frozen default_apps/sourceInputs',
 21:'meeting-recorder retained-delete implementation: portable Recorder pin is a different repository; no demonstrated ancestry/content equivalence',
 23:'meeting-recorder edge-take cleanup half has no demonstrated Recorder source equivalence',
 26:'meeting-recorder mic handoff/backend half has no demonstrated Recorder source equivalence',
 29:'private wizard-files release not selected (legacy files remains default)',
 31:'wizard-manager is not in frozen default_apps/sourceInputs',
 32:'private wizard-files release not selected',
 36:'private wizard-files-next release not selected; queue explicitly forbids global default change',
 39:'wizard-music app half is not selected; native Android half is out of guest scope',
 40:'wizard-manager release is not selected',
 41:'owner-local files-browser style commit has no remote and no portable packaged recipe selected',
 42:'wizard-manager release is not selected',
 43:'wizard-manager hosted-thread half is not selected',
 45:'Manager/Search/Video Editor app voice halves not selected; preserve optional/private configuration boundary',
 51:'wizard-manager orb destination half is not selected',
 54:'private Movies/cinequeue image/recipe not selected',
 75:'Wisdom private.15 is not selected',
 81:'security is a per-image runtime requirement, not satisfied by any source ancestor: CA/certifi/Node remediation and revoked-chain test pending'}
# Strong explicit reference checks for rows without a usable original commit,
# and reconciled successors where the old branch head was rewritten.
REFS = {
 2:{'wam':['b51e7b42','d6cf6cd9']},
 3:{'native':['02f9a00'],'wam':['850cfe32']},
 4:{'native':['dab55ba'],'service':['ee5229f']},
 11:{'native':['02f9a00'],'wam':['850cfe32']},
 24:{'service':['76367561']},
 25:{'ux':['4cdedced03a57c2dd95306b8375c1ef260b867a0']},
 45:{'service':['f24f921c7fb3ac8a9fcc4a88e5fa69b6c826a17e']},
 58:{'native':['d786206'],'wam':['cd3d0593'],'service':['6db5046']},
 74:{'native':['02f9a00'],'wam':['850cfe32']},
 79:{'native':['75c1f19f']},82:{'native':['75c1f19f']},
 83:{'service':['77650c65f9c80b999ffd78ee58a23ecd99bdfbeb']}}


def git(repo, *args):
    return subprocess.run(['git','-C',str(repo),*args],capture_output=True,text=True)


def make(pins, queue, repos):
    rows=[]
    for i,entry in enumerate(queue['entries'],1):
        text=entry['entry']; components=[]
        for key in CORE.get(i,'').split():
            pin=pins['finalPins'][key]; repo=repos/('release' if key=='native' else key)
            references=REFS.get(i,{}).get(key) or re.findall(r'(?<![0-9A-Za-z])([0-9a-f]{7,40})(?![0-9A-Za-z])',text)
            witnesses=[]
            for token in references:
                r=git(repo,'rev-parse','--verify',token+'^{commit}')
                if r.returncode:continue
                commit=r.stdout.strip()
                if git(repo,'merge-base','--is-ancestor',commit,pin).returncode==0:
                    witnesses.append({'queueReference':token,'commit':commit,'isAncestor':True})
            equivalent=[]
            if i==67 and key=='native':
                for file in ['next/mac/Shared/Brand.swift','next/mac/Tests/test-branding.py']:
                    previous=git(repo,'rev-parse','95f8176:'+file)
                    selected=git(repo,'rev-parse',pin+':'+file)
                    if previous.returncode==selected.returncode==0 and previous.stdout==selected.stdout:
                        equivalent.append({'path':file,'blob':selected.stdout.strip(),'reference':'95f8176'})
            proven=bool(witnesses) or (i==67 and key=='native' and len(equivalent)==2)
            components.append({'component':key,'pinnedCommit':pin,'ancestry':witnesses,'equivalentFiles':equivalent,
                               'status':'source-carried' if proven else 'not-proven'})
        reason=EXTERNAL.get(i)
        if i in (68,69):
            status='superseded';reason='Home hat policy superseded by row 66 (Home house); original branding and sizing ancestry recorded, not a request to restore old Home'
        elif i==13:
            status='no-guest-change';reason='Explicit Android-only queue row; APK is not part of guest assembly'
        elif reason or not components or any(c['status']!='source-carried' for c in components):status='not-fully-carried'
        else:status='source-carried'
        rows.append({'id':i,'queueLine':entry['queueLine'],'entry':text,'status':status,
                     'components':components,'reason':reason,'acceptance':'not-run-on-final-guest'})
    assert len(rows)==queue['entryCount']==84
    counts={s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}
    return {'schema':1,'queueSha256':queue['queueSha256'],'sourceSelectionSha256':hashlib.sha256(json.dumps(pins['finalPins'],sort_keys=True).encode()).hexdigest(),
            'entryCount':len(rows),'counts':counts,'notFullyCarried':[r['id'] for r in rows if r['status']=='not-fully-carried'],'entries':rows}


def main():
    p=argparse.ArgumentParser();p.add_argument('--repos',type=Path,required=True);a=p.parse_args()
    pins=json.loads((HERE/'pins.json').read_text());queue=json.loads((HERE/pins['queue']['manifest']).read_text())
    result=make(pins,queue,a.repos)
    (HERE/'queue-mapping.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='entries'},indent=2))


if __name__=='__main__':main()
