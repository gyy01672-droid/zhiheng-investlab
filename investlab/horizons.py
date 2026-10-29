"""Independent 60-session return model, temporal purge and unseen stock evaluation."""
import json
import numpy as np
import lightgbm as lgb
from .config import STATE,stamp
from . import models
def train(meta,datasets):
    records=[];held=[]
    for code in meta['training_symbols']+meta['heldout_symbols']:
        rows=datasets[code]['rows'];dest=records if code in meta['training_symbols'] else held
        for t,f in enumerate(models.features(rows),120):
            if t+60<len(rows):dest.append(dict(x=f['x'],date=f['date'],end=rows[t+60]['date'],y=rows[t+60]['close']/rows[t+1]['open']-1-.002))
    dates=sorted({r['date'] for r in records});a=dates[int(len(dates)*.6)];b=dates[int(len(dates)*.8)]
    groups=[[r for r in records if r['end']<a],[r for r in records if a<=r['date'] and r['end']<b],[r for r in records if r['date']>=b]]
    X=[np.array([r['x'] for r in g]) for g in groups];y=[np.array([r['y'] for r in g]) for g in groups]
    model=lgb.LGBMRegressor(n_estimators=220,num_leaves=15,min_child_samples=100,learning_rate=.03,n_jobs=8,verbosity=-1,random_state=27)
    model.fit(X[0],y[0],eval_set=[(X[1],y[1])],callbacks=[lgb.early_stopping(20,verbose=False)])
    def evaluate(g):
        yy=np.array([r['y'] for r in g]);pred=model.predict(np.array([r['x'] for r in g]));return {'samples':len(g),'mae':float(np.mean(abs(pred-yy))),'baseline_mae':float(np.mean(abs(np.mean(y[0])-yy))),'rmse':float(np.sqrt(np.mean((pred-yy)**2)))}
    result={'horizon':60,'created_at':stamp(),'parent_version':meta['version'],'test':evaluate(groups[2]),'unseen':evaluate([r for r in held if r['date']>=b]),'splits':[{ 'start':min(r['date'] for r in g),'end':max(r['date'] for r in g),'count':len(g)} for g in groups]}
    folder=STATE/'models'/meta['version'];(folder/'long.txt').write_text(model.booster_.model_to_string(),encoding='utf-8');(folder/'long.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
def predict(h,meta=None):
    meta=meta or models.info();folder=STATE/'models'/meta['version']
    if not (folder/'long.json').exists():return {'available':False,'message':'当前版本尚无独立60交易日模型，请训练新版'}
    info=json.loads((folder/'long.json').read_text(encoding='utf-8'));f=models.features(h['rows'])[-1]
    value=float(lgb.Booster(model_str=(folder/'long.txt').read_text(encoding='utf-8')).predict(np.array([f['x']]),num_threads=2)[0])
    useful=info['test']['mae']<info['test']['baseline_mae'] and info['unseen']['mae']<info['unseen']['baseline_mae']
    return dict(info,available=True,beats_baseline=useful,estimated_return=value,asof=f['date'],message='60交易日条件收益估计，非收益承诺；结合季报、盈利持续性与用款期限。MAE是历史平均误差，不是置信区间。'+('' if useful else '当前长期模型未优于常数基线，当前不生成长期股票推荐，保留现金并等待后续验证。'))
if __name__=='__main__':
    m=models.info();d=json.loads((STATE/'runs'/(m['version']+'-data.json')).read_text(encoding='utf-8'));print(json.dumps(train(m,d),ensure_ascii=False))
