"""Account-free public news; no private feeds or guaranteed delivery latency."""
import json,re,html,threading
from datetime import datetime
from . import market
from .config import CN,stamp,now

LOCK=threading.Lock()
FEED='https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&page=1&page_size=100'

def parse_feed(payload,fetched_at):
    result=payload.get('result',{})
    if result.get('status',{}).get('code')!=0:raise market.DataError('新浪快讯返回异常状态')
    rows=result.get('data',{}).get('feed',{}).get('list')
    if not isinstance(rows,list) or not rows:raise market.DataError('新浪快讯列表缺失或为空，不能确认覆盖')
    out=[]
    for r in rows:
        try:
            dt=datetime.fromisoformat(r['create_time']).replace(tzinfo=CN)
            ext=json.loads(r.get('ext') or '{}');text=html.unescape(re.sub('<[^>]+>','',r.get('rich_text',''))).strip()
            if not text:continue
            title=text.split('】',1)[0].lstrip('【') if text.startswith('【') else text[:110]
            out.append({'id':'SINA'+str(r['id']),'title':title,'content':text[:1500],'published_at':dt.isoformat(),'fetched_at':fetched_at,'source':'新浪财经7×24快讯','url':ext.get('docurl') or 'https://finance.sina.com.cn/7x24/','official':False,'stocks':ext.get('stocks',[])})
        except (ValueError,KeyError,TypeError):continue
    if not out:raise market.DataError('新浪快讯没有可识别的时间和正文')
    return sorted(out,key=lambda x:x['published_at'],reverse=True)

def flash():
    with LOCK:return market.cached('public-sina-flash:v1',60,lambda:parse_feed(json.loads(market.fetch(FEED)),stamp()))

def matches(item,code,name):
    # Prefer provider stock tags to avoid parent/subsidiary and similarly named firms.
    stocks=item.get('stocks',[])
    cn=[str(s.get('symbol','')).lower().removeprefix('sh').removeprefix('sz') for s in stocks if str(s.get('market','')).lower() in ['cn','sh','sz']]
    if cn:return code in cn
    if stocks:return False
    text=item.get('title','')+' '+item.get('content','')
    return bool(re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',text)) or len(name)>=3 and name in text

def company(code,name):return [r for r in flash() if matches(r,code,name)]

def check():
    sources=[];items=[]
    for label,fn in [('新浪财经7×24快讯',flash),('东方财富公司新闻检索',lambda:market.news('贵州茅台'))]:
        try:
            rows=fn();items.extend(rows[:5]);latest=max((r['published_at'] for r in rows),default=None)
            sources.append({'name':label,'ok':True,'count':len(rows),'latest_publication':latest,'fetched_at':rows[0].get('fetched_at') if rows else stamp()})
        except Exception as e:sources.append({'name':label,'ok':False,'error':str(e)})
    return {'sources':sources,'items':items,'checked_at':stamp(),'note':'无需登录或API密钥；快讯最多读取最近100条，检索结果有限且可能延迟。每轮巡检完成后120秒再检查，缓存60秒；不保证发布后两分钟内到达。'}
