"""Read-only live integration check. Does not alter user holdings or settings."""
import json,urllib.request,time
from pathlib import Path
BASE='http://127.0.0.1:8765/api/'
def call(path,data=None):
    req=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-InvestLab':'local'})
    with urllib.request.urlopen(req,timeout=300) as r:return json.load(r)
results={}
for name,path,data in [('status','status',None),('consult','consult?code=600519',None),('portfolio_stable','portfolio',{'budget':100000,'mode':'stable'}),('portfolio_aggressive','portfolio',{'budget':100000,'mode':'aggressive'}),('llm','explain',{'code':'600519'})]:
    start=time.time()
    try:
        result=call(path,data);results[name]={'ok':True,'seconds':round(time.time()-start,2),'result':result}
        print(name,'OK',round(time.time()-start,2),flush=True)
    except Exception as e:results[name]={'ok':False,'error':str(e)};print(name,'FAIL',str(e),flush=True)
    Path('output/live-verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
assert all(v['ok'] for v in results.values()),'Some live checks failed'
assert results['llm']['result']['validated'],'LLM response failed grounding guard'
