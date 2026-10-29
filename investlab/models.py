import json,time,hashlib,threading
import numpy as np
import lightgbm as lgb
from sklearn.metrics import f1_score,brier_score_loss
from sklearn.linear_model import LogisticRegression
from .config import STATE,UNIVERSE,stamp
from .market import history
from . import universe
from concurrent.futures import ThreadPoolExecutor,as_completed

LOCK=threading.Lock()
STATUS={'running':False,'message':'尚未训练'}
NAMES=['return_1','return_5','return_20','return_60','volatility_5','volatility_20','volatility_60','ma_gap_5','ma_gap_20','ma_gap_60','range','volume_ratio','drawdown_60','position_120']
def features(rows):
    c=np.array([r['close'] for r in rows]); v=np.array([r['volume'] for r in rows]); ret=np.diff(c)/c[:-1]
    out=[]
    for t in range(120,len(rows)):
        x=[c[t]/c[t-h]-1 for h in [1,5,20,60]]
        x += [float(np.std(ret[t-h:t])) for h in [5,20,60]]
        x += [c[t]/np.mean(c[t-h+1:t+1])-1 for h in [5,20,60]]
        x += [(rows[t]['high']-rows[t]['low'])/c[t],v[t]/max(np.mean(v[t-19:t+1]),1),c[t]/max(c[t-59:t+1])-1,float(np.mean(c[t-119:t+1]<=c[t]))]
        rec={'date':rows[t]['date'],'x':x}
        if t+5<len(rows):
            r=c[t+5]/rows[t+1]['open']-1-.002
            rec.update(end=rows[t+5]['date'],r=float(r),y=2 if r>.01 else (0 if r<-.01 else 1),lower=int(min(a['low'] for a in rows[t+1:t+6])<=c[t]*.97))
        out.append(rec)
    return out
def info():
    p=STATE/'models'/'active.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None
def train():
    from .joblock import exclusive
    with exclusive('training'):return _train()

def _train():
    if not LOCK.acquire(False):raise ValueError('训练已在运行')
    STATUS.update(running=True,message='下载历史日线')
    try:
        start=time.time(); samples=[]; datasets={}; failures={}
        directory=universe.current() or universe.refresh()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(history,code,True):code for code in directory['stocks']}
            for n,f in enumerate(as_completed(futures)):
                code=futures[f];STATUS['message']=f'更新历史日线 {n+1}/{len(futures)} {code}'
                try:
                    h=f.result()
                    if h['adjustment']!='qfq':raise ValueError('训练要求前复权日线')
                    datasets[code]=h
                except Exception as e:failures[code]=str(e)
        training_codes=[];heldout_codes=[];coverage={};missing={}
        for industry,group in directory['coverage'].items():
            valid=[code for code in group['codes'] if code in datasets and len(datasets[code]['rows'])>=300][:5]
            heldout=valid[-1:] if len(valid)>=4 else []
            train_codes=valid[:-1] if heldout else valid
            coverage[industry]={'train':train_codes,'heldout':heldout,'valid':len(valid)}
            if len(train_codes)<3:missing[industry]=len(train_codes)
            training_codes.extend(train_codes);heldout_codes.extend(heldout)
        for industry in directory['errors']:
            if industry not in coverage:missing[industry]=0
        if missing:
            (STATE/'runs'/'last-failure.json').write_text(json.dumps({'at':stamp(),'missing':missing,'failures':failures},ensure_ascii=False,indent=2),encoding='utf-8')
            raise ValueError('以下行业不足3只有效训练股票，本轮不发布模型：'+json.dumps(missing,ensure_ascii=False))
        for code in training_codes:
            samples.extend(dict(r,code=code) for r in features(datasets[code]['rows']) if 'y' in r)
        if len(training_codes)<30:raise ValueError('行业覆盖不足，保留旧模型')
        dates=sorted(set(r['date'] for r in samples)); a,b,c=[dates[int(len(dates)*f)] for f in [.6,.75,.85]]
        groups=[[r for r in samples if r['date']<a and r['end']<a],
                [r for r in samples if a<=r['date']<b and r['end']<b],
                [r for r in samples if b<=r['date']<c and r['end']<c],
                [r for r in samples if r['date']>=c]]
        if min(map(len,groups))<50:raise ValueError('时间隔离后的数据不足')
        X=[np.array([r['x'] for r in g]) for g in groups]
        ys=[np.array([r['y'] for r in g]) for g in groups]; ls=[np.array([r['lower'] for r in g]) for g in groups]
        STATUS['message']='CPU训练方向模型与下探模型'
        params=dict(n_estimators=350,num_leaves=15,learning_rate=.04,min_child_samples=70,verbosity=-1,n_jobs=8,random_state=27)
        direction=lgb.LGBMClassifier(**params)
        direction.fit(X[0],ys[0],eval_set=[(X[1],ys[1])],callbacks=[lgb.early_stopping(25,verbose=False)])
        lower=lgb.LGBMClassifier(**params)
        lower.fit(X[0],ls[0],eval_set=[(X[1],ls[1])],callbacks=[lgb.early_stopping(25,verbose=False)])
        cal=LogisticRegression(C=1)
        raw=np.clip(lower.predict_proba(X[2])[:,1],1e-6,1-1e-6)
        if len(set(ls[2]))<2:raise ValueError('校准区间只有一种类别')
        cal.fit(np.log(raw/(1-raw)).reshape(-1,1),ls[2])
        rawtest=np.clip(lower.predict_proba(X[3])[:,1],1e-6,1-1e-6)
        pl=cal.predict_proba(np.log(rawtest/(1-rawtest)).reshape(-1,1))[:,1]
        pd=direction.predict_proba(X[3]); base=float(np.mean(ls[0]))
        version=time.strftime('%Y%m%d-%H%M%S'); folder=STATE/'models'/version;folder.mkdir()
        (folder/'direction.txt').write_text(direction.booster_.model_to_string(),encoding='utf-8')
        (folder/'lower.txt').write_text(lower.booster_.model_to_string(),encoding='utf-8')
        # Non-overlapping five-session research backtest; no claim of full exchange execution.
        testdates=sorted(set(r['date'] for r in groups[3]));equity=benchmark=1.; curve=[]; trades=0
        for dt in testdates[::5]:
            ids=[i for i,r in enumerate(groups[3]) if r['date']==dt]
            selected=[i for i in ids if pd[i,2]>.45 and pl[i]<.4]
            gain=float(np.mean([groups[3][i]['r'] for i in selected])) if selected else 0.
            bench=float(np.mean([groups[3][i]['r'] for i in ids]))
            equity*=1+gain;benchmark*=1+bench;trades+=len(selected)
            curve.append({'date':dt,'strategy':equity,'benchmark':benchmark})
        vals=np.array([1.]+[x['strategy'] for x in curve]);dd=float(np.min(vals/np.maximum.accumulate(vals)-1))
        unseen=[dict(r,code=code) for code in heldout_codes for r in features(datasets[code]['rows']) if 'y' in r and r['date']>=c]
        ux=np.array([r['x'] for r in unseen]);uy=np.array([r['y'] for r in unseen]);ul=np.array([r['lower'] for r in unseen])
        ud=direction.predict_proba(ux);ur=np.clip(lower.predict_proba(ux)[:,1],1e-6,1-1e-6);up=cal.predict_proba(np.log(ur/(1-ur)).reshape(-1,1))[:,1]
        majority=int(np.bincount(ys[0]).argmax())
        unseen_metrics={'stock_count':len(heldout_codes),'samples':len(unseen),'macro_f1':float(f1_score(uy,ud.argmax(1),average='macro')),
                        'lower_brier':float(brier_score_loss(ul,up)),'baseline_brier':float(brier_score_loss(ul,np.full(len(ul),base))),
                        'majority_f1':float(f1_score(uy,np.full(len(uy),majority),average='macro'))}
        champion=info();comparison=None
        if champion:
            oldfolder=STATE/'models'/champion['version']
            oldraw=np.clip(lgb.Booster(model_str=(oldfolder/'lower.txt').read_text(encoding='utf-8')).predict(ux,num_threads=8),1e-6,1-1e-6)
            oldcal=champion['calibration'];oldp=1/(1+np.exp(-(oldcal['coef']*np.log(oldraw/(1-oldraw))+oldcal['intercept'])))
            comparison={'version':champion['version'],'same_unseen_brier':float(brier_score_loss(ul,oldp)),'candidate_brier':unseen_metrics['lower_brier']}
        manifest={'version':version,'schema_version':2,'created_at':stamp(),'stock_count':len(training_codes),'sample_count':len(samples),
          'training_symbols':training_codes,'heldout_symbols':heldout_codes,'industry_coverage':coverage,'universe_updated_at':directory['updated_at'],
          'industry_source':directory['classification'],'unseen_metrics':unseen_metrics,'champion_comparison':comparison,'evaluation_dates':testdates,
          'feature_bounds':{'low':np.quantile(X[0],.01,axis=0).tolist(),'high':np.quantile(X[0],.99,axis=0).tolist()},
          'features':NAMES,'splits':{name:{'count':len(g),'start':min(r['date'] for r in g),'end':max(r['date'] for r in g)} for name,g in zip(['train','validation','calibration','test'],groups)},
          'calibration':{'coef':float(cal.coef_[0,0]),'intercept':float(cal.intercept_[0])},
          'metrics':{'macro_f1':float(f1_score(ys[3],pd.argmax(1),average='macro')),'majority_f1':float(f1_score(ys[3],np.full(len(ys[3]),majority),average='macro')),'lower_brier':float(brier_score_loss(ls[3],pl)),'baseline_brier':float(brier_score_loss(ls[3],np.full(len(pl),base))),'test_event_rate':float(np.mean(ls[3]))},
          'backtest':{'return_pct':(equity-1)*100,'benchmark_pct':(benchmark-1)*100,'max_drawdown_pct':dd*100,'trades':trades,'curve':curve,
          'limitations':'研究性五日非重叠回放；费用假设0.2%；未建模涨跌停、退市和真实成交冲击；当前股票池存在幸存者偏差。'},
          'seconds':round(time.time()-start,2),'failures':failures,'training_device':'CPU','horizon':5,'threshold':.03,
          'data_sha256':hashlib.sha256(json.dumps(datasets,sort_keys=True).encode()).hexdigest()}
        (STATE/'runs'/f'{version}-data.json').write_text(json.dumps(datasets,ensure_ascii=False),encoding='utf-8')
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        from . import horizons
        horizons.train(manifest,datasets)
        # Auto update never silently promotes a candidate. First training is initial baseline.
        if not info():activate(version)
        STATUS.update(message='训练完成；候选模型已保存',result=manifest)
        return manifest
    except Exception as e:STATUS['message']='训练失败：'+str(e);raise
    finally:STATUS['running']=False;LOCK.release()
def activate(version):
    import re
    if not re.fullmatch(r'\d{8}-\d{6}',version):raise ValueError('版本格式错误')
    p=STATE/'models'/version/'manifest.json'
    if not p.exists():raise ValueError('版本不存在')
    dest=STATE/'models'/'active.json'; tmp=dest.with_suffix('.tmp');tmp.write_bytes(p.read_bytes());tmp.replace(dest)
def predict(code,h=None,meta=None):
    meta=meta or info()
    if not meta:return {'available':False,'message':'请先在实验室训练本地判断模型'}
    h=h or history(code); fs=features(h['rows']);x=np.array([fs[-1]['x']]);folder=STATE/'models'/meta['version']
    pd=lgb.Booster(model_str=(folder/'direction.txt').read_text(encoding='utf-8')).predict(x,num_threads=2)[0]
    raw=float(lgb.Booster(model_str=(folder/'lower.txt').read_text(encoding='utf-8')).predict(x,num_threads=2)[0]);raw=np.clip(raw,1e-6,1-1e-6)
    cal=meta['calibration'];low=float(1/(1+np.exp(-(cal['coef']*np.log(raw/(1-raw))+cal['intercept']))))
    closes=np.array([r['close'] for r in h['rows'][-252:]]);position=float(np.mean(closes<=closes[-1]))
    reliable=meta['metrics']['lower_brier']<meta['metrics']['baseline_brier']
    normalized=str(code).lower().replace('sh','').replace('sz','')
    seen=normalized in meta.get('training_symbols',[])
    bounds=meta.get('feature_bounds');outside=int(np.sum((x[0]<bounds['low'])|(x[0]>bounds['high']))) if bounds else None
    return {'available':True,'version':meta['version'],'asof':fs[-1]['date'],'down':float(pd[0]),'flat':float(pd[1]),'up':float(pd[2]),'lower':low,'position':position,
       'position_label':'相对低位' if position<=.2 else ('相对高位' if position>=.8 else '中位区间'),
       'engine':'LightGBM','input_sha256':hashlib.sha256(json.dumps(fs[-1],sort_keys=True).encode()).hexdigest(),'features':dict(zip(NAMES,fs[-1]['x'])),'direction_beats_baseline':meta['metrics']['macro_f1']>meta['metrics']['majority_f1'],'direction_calibrated':False,'classes':{'up':'未来第5交易日收盘相对下一交易日开盘，扣0.2%假设费用后收益超过1%','flat':'上述净收益介于负1%与正1%之间','down':'上述净收益低于负1%'},'research_only':True,'beats_baseline':reliable,'in_training':seen,'out_of_range_features':outside,
       'scope_note':'曾参与训练，仍可能预测错误' if seen else '未参与训练，属于跨股票泛化；可以联网取资料，但不能保证预测正确',
       'message':'未来5交易日下探至少3%的估计概率；历史位置不等于估值。'+('' if reliable else '当前下探模型测试未优于常数基线，谨慎解读。')+('预设策略历史回放亏损且落后基准，仅供研究。' if meta['backtest']['return_pct']<min(0,meta['backtest']['benchmark_pct']) else '')}
if __name__=='__main__':print(json.dumps(train(),ensure_ascii=False,indent=2))
