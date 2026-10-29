import threading,time
from datetime import datetime,timedelta
from . import store,market,models
from .config import stamp,now,CN

LOCK=threading.Lock()
STATE={'running':False,'next_scan':None,'last_error':None}
TERMS=['立案','处罚','财务造假','违约','退市','重大诉讼','业绩预亏','亏损','减持','事故','被调查','下调']

def classify(item):
    text=item.get('title','')+' '+item.get('content','')
    hits=[w for w in TERMS if w in text]
    if not hits:return None
    # Rule screening never turns a rumor, denial or keyword hit into a sell order.
    denial=any(w in text for w in ['不存在','不涉及','未发生','不属实','澄清','辟谣','终止减持'])
    return {'level':'待核实' if denial or not item.get('official') else '重点核查',
            'terms':hits,'method':'关键词初筛','denial_detected':denial,
            'action':'核对公告原文、事件日期及持仓风险；由用户决定是否调整仓位。'}

def scan():
    if not LOCK.acquire(False):raise ValueError('巡检正在进行')
    STATE.update(running=True,last_error=None);started=stamp();errors={};added=0;checked=0
    try:
        codes=store.open_codes()
        for code in codes:
            try:
                ev=market.evidence(code);checked+=1
                if ev['errors']:errors[code]='；'.join(ev['errors'])
                for item in ev['items']:
                    try:
                        dt=datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))
                        if dt.tzinfo is None:dt=dt.replace(tzinfo=CN)
                        if dt<now()-timedelta(hours=72) or dt>now()+timedelta(hours=1):continue
                    except ValueError:continue
                    verdict=classify(item)
                    if verdict:
                        item=dict(item,screening=verdict)
                        added+=int(store.save_event(code,item,verdict['level']))
            except Exception as e:errors[code]=str(e)
        result={'holdings_checked':checked,'new_events':added,'errors':errors,'coverage':'公开公告、东方财富公司新闻和新浪财经7×24快讯；有限覆盖，失败见错误记录'}
        with store.db() as c:
            import json
            c.execute('INSERT INTO scans(started_at,ended_at,status,detail) VALUES (?,?,?,?)',(started,stamp(),'部分失败' if errors else '完成',json.dumps(result,ensure_ascii=False)))
        return result
    except Exception as e:STATE['last_error']=str(e);raise
    finally:STATE['running']=False;LOCK.release()

def import_item(data):
    code=market.symbol(data['code'])[2:];text=str(data.get('text','')).strip()
    if not text or len(text)>10000:raise ValueError('请输入1至10000字舆情内容')
    item={'title':text[:100],'content':text,'published_at':stamp(),'source':'用户手动导入（未经独立核实）','official':False,'url':''}
    v=classify(item) or {'level':'待核实','terms':[],'method':'用户导入','action':'请核对原始来源'}
    item['screening']=v;store.save_event(code,item,v['level']);return item

def scheduler():
    next_scan=0
    while True:
        try:
            if store.get_setting('monitor',True):
                if time.time()>=next_scan:
                    scan();next_scan=time.time()+120
                STATE['next_scan']=datetime.fromtimestamp(next_scan,CN).isoformat(timespec='seconds')
            else:next_scan=0;STATE['next_scan']=None
        except Exception as e:STATE['last_error']=str(e)
        try:
            from . import bots
            bots.tick()
        except Exception:STATE['last_error']='机器人通知处理失败，请检查通知面板'
        time.sleep(10)
