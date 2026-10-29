"""Versioned public industry directory. Provider classification, not a claim of SW 2021."""
import json,re,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from .config import STATE,stamp,UNIVERSE
from .market import fetch

PATH=STATE/'universe.json'
LOCK=threading.Lock()
STATUS={'running':False,'message':'尚未更新行业目录'}

def current():
    if PATH.exists():return json.loads(PATH.read_text(encoding='utf-8'))
    return None

def install(record):
    UNIVERSE.clear();UNIVERSE.update({k:(v['name'],v['industry']) for k,v in record['stocks'].items()})

def refresh():
    if not LOCK.acquire(False):raise ValueError('行业目录正在更新')
    STATUS.update(running=True,message='读取新浪公开行业目录')
    try:
        raw=fetch('https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php','gb18030')
        groups=json.loads(raw[raw.index('{'):raw.rindex('}')+1]);errors={};baskets={}
        # 次新股 is a listing-age group, not an industry. Keep all other source categories.
        groups={k:v.split(',')[1] for k,v in groups.items() if v.split(',')[1]!='次新股'}
        def members(item):
            node,name=item
            url='https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=40&sort=mktcap&asc=0&node='+node
            data=json.loads(fetch(url));out=[]
            if not isinstance(data,list):raise ValueError('成员列表格式错误')
            for r in data:
                code=str(r.get('code',''));title=r.get('name','')
                if not re.fullmatch(r'[036]\d{5}',code) or 'ST' in title.upper() or '退' in title:continue
                if float(r.get('trade') or 0)<=0 or float(r.get('volume') or 0)<=0:continue
                out.append({'code':code,'name':title,'industry':name,'market_cap':float(r.get('mktcap') or 0)})
            return name,out
        with ThreadPoolExecutor(max_workers=4) as pool:
            fs={pool.submit(members,x):x[1] for x in groups.items()}
            for i,f in enumerate(as_completed(fs)):
                name=fs[f];STATUS['message']=f'行业成员 {i+1}/{len(groups)}：{name}'
                try:name,rows=f.result();baskets[name]=rows
                except Exception as e:errors[name]=str(e)
        stocks={};coverage={}
        for name in sorted(baskets):
            # Keep extra candidates so history-quality failures can be replaced automatically.
            candidates=[r for r in baskets[name] if r['code'] not in stocks][:8]
            for r in candidates:stocks[r['code']]=r
            coverage[name]={'candidates':len(candidates),'codes':[r['code'] for r in candidates]}
            if len(candidates)<3:errors[name]=f'有效候选仅{len(candidates)}只，不足3只'
        record={'updated_at':stamp(),'source':'新浪公开行业分类','classification':'新浪行业目录（非申万2021；排除次新股）',
                'source_url':'https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php','industry_count':len(groups),
                'stocks':stocks,'coverage':coverage,'errors':errors,'target_per_industry':5,'minimum_training_per_industry':3}
        if len(stocks)<30:raise ValueError('有效股票过少，保留原行业目录')
        tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(PATH)
        install(record);STATUS['message']=f'目录更新完成：{len(groups)}类，{len(stocks)}只候选'
        return record
    finally:STATUS['running']=False;LOCK.release()

if current():install(current())
