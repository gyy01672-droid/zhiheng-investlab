"""Independent data refresh / candidate training / gated promotion service."""
import json,threading,time
from datetime import datetime,timedelta
from .config import STATE,stamp,now
from . import market,models,store,universe

LOCK=threading.Lock()
STATUS={'running':False,'message':'等待自动更新','last_error':None}
LOG=STATE/'update-history.json'
KNOWLEDGE=STATE/'knowledge';KNOWLEDGE.mkdir(exist_ok=True)

def history():
    if LOG.exists():return json.loads(LOG.read_text(encoding='utf-8'))
    return []

def remember(code):
    code=market.symbol(code)[2:]
    codes=store.get_setting('watched_codes',[])
    if code not in codes:store.setting('watched_codes',(codes+[code])[-100:])

def save_knowledge(code,evidence):
    import uuid
    path=KNOWLEDGE/(market.symbol(code)[2:]+'.json')
    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def promotion_check(candidate):
    active=models.info();reasons=[]
    if not candidate.get('industry_coverage') or any(len(g['train'])<3 for g in candidate['industry_coverage'].values()):reasons.append('行业训练覆盖不足')
    unseen=candidate.get('unseen_metrics',{})
    if unseen.get('samples',0)<500:reasons.append('未见股票测试样本不足')
    if unseen.get('lower_brier',1)>=unseen.get('baseline_brier',0):reasons.append('未见股票下探误差未优于常数基线')
    if unseen.get('macro_f1',0)<=unseen.get('majority_f1',1):reasons.append('未见股票方向分数未优于多数类基线')
    long_path=STATE/'models'/candidate.get('version','')/'long.json'
    if not long_path.exists():reasons.append('缺少独立长期模型验证结果')
    else:
        long_info=json.loads(long_path.read_text(encoding='utf-8'))
        if any(long_info[k]['mae']>=long_info[k]['baseline_mae'] for k in ['test','unseen']):reasons.append('长期模型未同时优于已见和未见股票常数基线')
    backtest=candidate.get('backtest',{})
    if backtest.get('return_pct',0)<min(0,backtest.get('benchmark_pct',0)):reasons.append('研究回放亏损且落后等权基准，禁止自动启用')
    comparison=candidate.get('champion_comparison')
    if comparison and comparison['candidate_brier']>comparison['same_unseen_brier']*1.01:reasons.append('相同评估样本上未达到当前版本误差门槛')
    if active and active.get('schema_version')==2:
        after=active['splits']['test']['end']
        fresh=[d for d in candidate.get('evaluation_dates',[]) if d>after]
        if len(fresh)<20:reasons.append('相对当前版本新增成熟测试交易日不足20天，继续积累')
    return {'eligible':not reasons,'reasons':reasons,'note':'自动门槛控制版本更替，不保证投资收益；仍需长期前向验证。'}

def run(train=False,refresh_universe=False):
    from .joblock import exclusive
    with exclusive('updating'):return _run(train,refresh_universe)

def _run(train=False,refresh_universe=False):
    if not LOCK.acquire(False):raise ValueError('更新任务已经运行')
    STATUS.update(running=True,message='开始更新公开资料',last_error=None)
    result={'started_at':stamp(),'training_requested':train,'errors':{},'updated_codes':[]}
    try:
        directory=universe.current()
        age=(now()-datetime.fromisoformat(directory['updated_at'])).total_seconds() if directory else 1e10
        if refresh_universe or age>7*86400:
            STATUS['message']='更新行业目录与股票成员';directory=universe.refresh()
        codes=list(dict.fromkeys(store.open_codes()+store.get_setting('watched_codes',[])))[:40]
        for i,code in enumerate(codes):
            STATUS['message']=f'更新关注公司资料 {i+1}/{len(codes)}'
            try:
                ev=market.evidence(code);save_knowledge(code,ev);market.history(code,refresh=True)
                result['updated_codes'].append(code)
                if ev['errors']:result['errors'][code]='；'.join(ev['errors'])
            except Exception as e:result['errors'][code]=str(e)
        store.setting('last_data_refresh',stamp())
        if train:
            STATUS['message']='在本机训练新的判断模型候选'
            candidate=models.train();gate=promotion_check(candidate)
            result.update(candidate=candidate['version'],promotion=gate)
            if store.get_setting('auto_promote',True) and gate['eligible']:
                models.activate(candidate['version']);result['activated']=True
            else:result['activated']=False
            store.setting('last_train_success',stamp())
        STATUS['message']='更新完成'+('；候选模型已评估' if train else '')
        result['status']='部分来源失败' if result['errors'] else '完成'
        return result
    except Exception as e:
        result.update(status='失败',error=str(e));STATUS.update(last_error=str(e),message='更新失败；已保留当前模型');raise
    finally:
        result['ended_at']=stamp();logs=history();logs.insert(0,result)
        temp=LOG.with_suffix('.tmp');temp.write_text(json.dumps(logs[:100],ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(LOG)
        STATUS['running']=False;LOCK.release()

def scheduler():
    last_retry=0
    while True:
        try:
            if not STATUS['running'] and time.time()-last_retry>900:
                day=now().date().isoformat()
                due_train=store.get_setting('selflearn',True) and now().weekday()<5 and (now().hour*60+now().minute)>=975 and store.get_setting('last_train_attempt_day')!=day
                recent=store.get_setting('last_data_refresh')
                age=(now()-datetime.fromisoformat(recent)).total_seconds() if recent else 1e10
                due_data=store.get_setting('auto_data',True) and age>=900
                if due_train or due_data:
                    last_retry=time.time()
                    if due_train:store.setting('last_train_attempt_day',day)
                    run(train=due_train)
        except Exception as e:STATUS['last_error']=str(e)
        time.sleep(20)
