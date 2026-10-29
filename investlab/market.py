import json, re, time, hashlib, urllib.request, urllib.parse, threading
from datetime import datetime,timedelta,date
from .config import STATE, CN, now, stamp, UNIVERSE

class DataError(Exception): pass
_cache_lock=threading.RLock()
def symbol(code):
    code=str(code).strip().lower().replace('.sh','').replace('.sz','')
    code=re.sub(r'^(sh|sz)','',code)
    if not re.fullmatch(r'\d{6}',code): raise ValueError('请输入六位A股代码，例如600519')
    if code[0] not in '036': raise ValueError('当前版本支持沪深A股，暂不支持北交所及其他品种')
    return ('sh' if code[0]=='6' else 'sz')+code
def fetch(url,decode='utf-8',maxbytes=8_000_000):
    last=None
    for attempt in range(2):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 LocalInvestmentResearch/1.0','Referer':'https://finance.qq.com/'})
            with urllib.request.urlopen(req,timeout=18) as r:
                b=r.read(maxbytes+1)
                if len(b)>maxbytes: raise DataError('来源响应超过大小限制')
                return b.decode(decode,errors='replace')
        except Exception as e:
            last=e
            if attempt==0: time.sleep(.4)
    raise DataError('数据源暂时不可用：'+str(last))
def cached(key,ttl,loader):
    p=STATE/'cache'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
    with _cache_lock:
        if p.exists():
            j=json.loads(p.read_text(encoding='utf-8'))
            if time.time()-j['time']<ttl: return j['value']
    value=loader()
    with _cache_lock:
        temp=p.with_suffix('.tmp'); temp.write_text(json.dumps({'time':time.time(),'value':value},ensure_ascii=False),encoding='utf-8'); temp.replace(p)
    return value
def quote(code):
    sym=symbol(code)
    def load():
        s=fetch('https://qt.gtimg.cn/q='+sym,'gb18030')
        m=re.search(r'="(.*?)"',s,re.S)
        parts=m.group(1).split('~') if m else []
        if len(parts)<46 or not parts[3] or float(parts[3])<=0: raise DataError('未取得有效行情，请检查代码或证券状态')
        ts=datetime.strptime(parts[30],'%Y%m%d%H%M%S').replace(tzinfo=CN)
        q={'symbol':sym,'code':sym[2:],'name':parts[1],'price':float(parts[3]),'previous_close':float(parts[4]),
           'change_pct':float(parts[32]),'open':float(parts[5]),'high':float(parts[33]),'low':float(parts[34]),
           'volume_lots':float(parts[6]),'quote_time':ts.isoformat(),'fetched_at':stamp(),'source':'腾讯证券公开行情',
           'source_url':'https://gu.qq.com/'+sym,'industry':UNIVERSE.get(sym[2:],('', '其他'))[1]}
        return q
    q=dict(cached('quote:'+sym,20,load))
    age=(now()-datetime.fromisoformat(q['quote_time'])).total_seconds()
    minute=now().hour*60+now().minute
    session=now().weekday()<5 and (570<=minute<=690 or 780<=minute<=900)
    q['stale']=age< -60 or age> (300 if session else 4*86400)
    q['age_seconds']=max(0,int(age));q['cache_seconds']=20
    q['freshness']='过期或时钟异常' if q['stale'] else ('交易时段报价' if session else '休市期间最近报价')
    q['timeliness_note']='公开接口无延迟SLA；时间取自数据源。页面每30秒刷新，最多20秒本地报价缓存；交易时段超过5分钟标为过期。节假日暂按工作日估算。'
    q['market_status']='交易时段（按工作日估算）' if session else '非交易时段 / 最近报价'
    return q

def trade_reference(code,when):
    sym=symbol(code);day=date.fromisoformat(str(when)[:10])
    if day>now().date():raise ValueError('不能查询未来成交日期')
    if day==now().date() and now().hour<15:
        q=quote(code)
        if q['quote_time'][:10]!=day.isoformat() or q['stale']:raise DataError('当天没有有效盘中报价，请手动填入成交价')
        return {'price':q['price'],'date':day.isoformat(),'basis':'当日盘中最新报价','adjustment':'raw','confirmed':False,'quote_time':q['quote_time'],
                'warning':'参考报价不是您的实际成交价，请按成交记录修改并确认。'}
    def load():
        param=f'{sym},day,{day-timedelta(days=7)},{day+timedelta(days=1)},60,'
        u='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?'+urllib.parse.urlencode({'param':param},safe=',')
        try:
            data=json.loads(fetch(u)).get('data',{}).get(sym,{})
            rows=data.get('day',[]);source='腾讯历史日线'
        except Exception:
            rows,u=sina_daily(sym,False);source='新浪未复权日线'
        row=next((r for r in rows if r[0]==day.isoformat()),None)
        if row is None:raise DataError('该日期无未复权日线，可能为休市、停牌或超出数据范围；请核对日期或手动输入')
        return {'price':float(row[2]),'date':day.isoformat(),'basis':'当日未复权收盘价','adjustment':'raw','confirmed':False,'source':source,'source_url':u,
                'warning':'收盘价只是预填参考，不是您的真实成交价；请核对实际成交价和费用。'}
    return cached(f'trade-reference:{sym}:{day}',60 if day==now().date() else 86400,load)
def sina_daily(sym,adjust=True):
    import bisect,math
    u=f'https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=1023'
    raw=fetch(u);rows=json.loads(raw[raw.index('([')+1:raw.rindex('])')+1])
    factors=[]
    if adjust:
        fu=f'https://finance.sina.com.cn/realstock/company/{sym}/qfq.js';text=fetch(fu)
        obj=json.JSONDecoder().raw_decode(text[text.index('=')+1:].lstrip())[0]
        factors=sorted((r['d'],float(r['f'])) for r in obj['data'])
        if not factors or any(not math.isfinite(f) or f<=0 for _,f in factors):raise DataError('复权因子缺失或无效')
    out=[];days=[d for d,_ in factors]
    for row in rows:
        day=row['day'][:10];factor=1.
        if adjust:
            ix=bisect.bisect_right(days,day)-1
            if ix<0:continue
            factor=factors[ix][1]
        out.append([day]+[float(row[k])/factor for k in ['open','close','high','low']]+[float(row['volume'])])
    return out,u

def history(code,refresh=False):
    sym=symbol(code)
    def load():
        source_errors=[]
        try:
            rows,u=sina_daily(sym);source='新浪日线 + 新浪前复权因子';adjustment='qfq'
        except Exception as se:
            source_errors.append(str(se))
            secid=('1.' if sym.startswith('sh') else '0.')+sym[2:]
            u='https://push2his.eastmoney.com/api/qt/stock/kline/get?'+urllib.parse.urlencode({'secid':secid,'klt':101,'fqt':1,'lmt':1000,'end':'20500101','fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'},safe=',')
            source='东方财富前复权日线';adjustment='qfq';source_errors=[]
            try:
                j=json.loads(fetch(u));block=j.get('data') or {};rows=[r.split(',')[:6] for r in block.get('klines',[])]
                if len(rows)<150:raise DataError('有效历史不足150日')
            except Exception as e:
                source_errors.append(str(e));u='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?'+urllib.parse.urlencode({'param':f'{sym},day,,,640,qfq'},safe=',')
                j=json.loads(fetch(u));block=j.get('data',{}).get(sym,{})
                rows=block.get('qfqday') or block.get('day') or []
                adjustment='qfq' if block.get('qfqday') else 'raw';source='腾讯证券历史日线（备用）'
        out=[]
        for r in rows:
            try:
                vals=list(map(float,r[1:6]))
                op,cl,hi,lo,vol=vals
                if min(op,cl,hi,lo)<=0 or hi<max(op,cl,lo) or lo>min(op,cl,hi) or vol<0: continue
                if r[0]==now().date().isoformat() and now().hour*60+now().minute<915: continue
                out.append({'date':r[0],'open':op,'close':cl,'high':hi,'low':lo,'volume':vol})
            except (ValueError,IndexError): continue
        out=list({x['date']:x for x in out}.values()); out.sort(key=lambda x:x['date'])
        if len(out)<150: raise DataError('有效历史不足150个交易日，不能训练或判断')
        return {'symbol':sym,'rows':out,'adjustment':adjustment,
                'source':source,'fetched_at':stamp(),'source_url':u,'source_errors':source_errors}
    return cached('history:'+sym,0 if refresh else 3600,load)
def announcements(code):
    code=symbol(code)[2:]
    def load():
        u='https://np-anotice-stock.eastmoney.com/api/security/ann?'+urllib.parse.urlencode({'sr':-1,'page_size':30,'page_index':1,'ann_type':'A','stock_list':code})
        data=json.loads(fetch(u)).get('data',{})
        if not isinstance(data,dict): raise DataError('公告数据格式发生变化')
        out=[]
        for a in data.get('list',[]):
            aid=a.get('art_code','')
            if not re.fullmatch(r'AN\d+',aid): continue
            out.append({'id':aid,'title':a.get('title',''),'published_at':a.get('notice_date','')[:19],
                        'source':'上市公司公告（东方财富索引）','url':f'https://data.eastmoney.com/notices/detail/{code}/{aid}.html',
                        'official':True,'content':''})
        return out
    return cached('ann:v2:'+code,60,load)
def announcement_content(aid):
    if not re.fullmatch(r'AN\d+',aid): raise ValueError('无效公告编号')
    def load():
        u='https://np-cnotice-stock.eastmoney.com/api/content/ann?'+urllib.parse.urlencode({'art_code':aid,'client_source':'web','page_index':1})
        j=json.loads(fetch(u)).get('data',{})
        if not isinstance(j,dict): raise DataError('公告正文暂不可用')
        return {'id':aid,'text':j.get('notice_content','')[:50000],'title':j.get('notice_title',''),
                'pdf_url':j.get('attach_url',''),'fetched_at':stamp()}
    return cached('anncontent:'+aid,86400,load)
def news(name):
    def load():
        p={'uid':'','keyword':name,'type':['cmsArticleWebOld'],'client':'web','clientType':'web','clientVersion':'curr',
           'param':{'cmsArticleWebOld':{'searchScope':'default','sort':'default','pageIndex':1,'pageSize':15,'preTag':'','postTag':''}}}
        u='https://search-api-web.eastmoney.com/search/jsonp?'+urllib.parse.urlencode({'cb':'cb','param':json.dumps(p,ensure_ascii=False)})
        s=fetch(u); j=json.loads(s[s.index('(')+1:s.rindex(')')])
        if j.get('code')!=0: raise DataError('新闻检索接口返回错误')
        return [{'id':'NEWS'+str(a.get('code','')),'title':re.sub('<[^>]+>','',a.get('title','')),
                 'content':re.sub('<[^>]+>','',a.get('content',''))[:1500],'published_at':a.get('date',''),
                 'source':a.get('mediaName','新闻检索'),'url':a.get('url',''),'official':False,'fetched_at':stamp()}
                for a in j.get('result',{}).get('cmsArticleWebOld',[]) if name in a.get('title','')+a.get('content','')]
    return cached('news:v2:'+name,60,load)
def evidence(code):
    from . import public_news
    q=quote(code); items=[]; errors=[]
    for label,call in [('公告',lambda:announcements(code)),('公司新闻',lambda:news(q['name'])),('财经快讯',lambda:public_news.company(code,q['name']))]:
        try: items.extend(call())
        except Exception as e: errors.append(label+'：'+str(e))
    items=list({(i['title'],i['published_at'][:10]):i for i in items}.values())
    items.sort(key=lambda x:x['published_at'],reverse=True)
    return {'items':items,'errors':errors,'coverage':'公开公司公告 + 东方财富新闻检索 + 新浪财经7×24快讯；不含社交平台，有限覆盖，失败见下方记录。', 'fetched_at':stamp()}
