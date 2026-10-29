"""Constrained, long-only research allocation from local models and observed prices."""
import math
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
from .config import UNIVERSE,stamp
from . import market,models,profile,horizons

def round_positions(candidates,weights,budget,fee_rate=.001):
    rows=[]
    for c,w in zip(candidates,weights):
        quantity=int(math.floor((budget*float(w))/(c['quote']['price']*100*(1+fee_rate))))*100
        if quantity<=0:continue
        value=round(quantity*c['quote']['price'],2);fee=round(value*fee_rate,2)
        rows.append({'code':c['code'],'name':c['quote']['name'],'industry':c['quote']['industry'],
                     'price':c['quote']['price'],'quantity':quantity,'amount':value,'fee':fee,
                     'weight':value/budget,'quote_time':c['quote']['quote_time']})
    spent=round(sum(r['amount']+r['fee'] for r in rows),2)
    if spent>budget+.01:raise ValueError('整手换算超过预算')
    return rows,round(budget-spent,2)

def allocate(budget,mode,horizon='short',stock_budget=None,rotation=0):
    from . import advice
    budget=float(budget);rotation=int(rotation)
    if not math.isfinite(budget) or budget<=500 or budget>1e9:raise ValueError('总资金需大于500元且不超过10亿元')
    if mode not in ['stable','aggressive']:raise ValueError('请选择稳健型或进取型')
    if not 0<=rotation<=10000:raise ValueError('候选轮次无效')
    meta=models.info()
    if not meta:raise ValueError('请先完成判断模型训练')
    policy=profile.policy(horizon)
    target_amount=round(budget*(.65 if mode=='stable' else .85),2) if stock_budget in [None,''] else float(stock_budget)
    if not math.isfinite(target_amount) or target_amount<0 or target_amount>budget:raise ValueError('拟投入金额应在0与总预算之间')
    warning=policy['message']+('；本次目标超过画像参考比例，请复核承受能力。' if target_amount/budget>policy['equity_cap'] else '')
    failed={}
    if target_amount==0:return summarize([],budget,0,mode,horizon,failed,policy,warning+'；按画像保留全部现金。',0)
    pool_codes=[]
    for g in meta.get('industry_coverage',{}).values():
        eligible=[c for c in g['train'] if not c.startswith(('688','300','301'))]
        pool_codes.extend(eligible[(rotation+i)%len(eligible)] for i in range(min(2,len(eligible))))
    pool_codes=list(dict.fromkeys(pool_codes or list(UNIVERSE)[:20]))
    def preliminary(code):
        try:
            c=advice.quantitative(code,horizon,meta)
            reason=advice.signal_rejection(c)
            if reason:raise ValueError(reason)
            if c['quote']['price']*100*1.001>target_amount:raise ValueError('目标资金不足一手')
            return c
        except Exception as e:failed[code]=str(e);return None
    with ThreadPoolExecutor(max_workers=4) as pool:cs=[c for c in pool.map(preliminary,pool_codes) if c]
    cs.sort(key=lambda c:c['prediction']['up']-c['prediction']['down']-.3*c['prediction']['lower'],reverse=True)
    def review(c):
        try:
            c=advice.consultation(c['code'],horizon,snapshot=c)
            if not c['eligibility']['passed']:raise ValueError(c['eligibility']['reason'])
            return c
        except Exception as e:failed[c['code']]=str(e);return None
    with ThreadPoolExecutor(max_workers=3) as pool:cs=[c for c in pool.map(review,cs[:18]) if c]
    if not cs:
        out=summarize([],budget,target_amount,mode,horizon,failed,policy,'当前没有同时满足模型信号、报价、预算及咨询复核的股票；保留现金，不为填满仓位放宽筛选。'+warning,0)
        out.update(alternatives=[],singles=[],rotation=rotation,screened=len(pool_codes),approved=0);return out
    plans=[];seen=set()
    orders=[('均衡分散',cs,1.),('低下探候选',sorted(cs,key=lambda c:c['prediction']['lower']),1.8),('信号集中型',sorted(cs,key=lambda c:c['prediction']['up']-c['prediction']['down'],reverse=True),.65)]
    for title,ordered,scale in orders:
        subset=ordered[:(6 if title=='均衡分散' else 4 if title=='低下探候选' else 3)]
        p=optimize(subset,budget,target_amount,mode,horizon,failed,policy,warning,scale)
        signature=tuple(sorted((r['code'],r['quantity']) for r in p['positions']))
        if signature in seen:continue
        seen.add(signature);p.update(title=title,plan_id='portfolio-'+str(len(plans)+1));plans.append(p)
    singles=[]
    for c in cs[:6]:
        rows,_=fill_lots([c],[target_amount/budget],budget,target_amount)
        p=summarize(rows,budget,target_amount,mode,horizon,failed,policy,'单股备选，有集中风险；通过同一咨询复核不代表保证上涨。'+warning,None)
        p.update(title=c['quote']['name']+' · 单股备选',plan_id='single-'+c['code']);singles.append(p)
    out=dict(plans[0]);out.update(alternatives=plans,singles=singles,rotation=rotation,screened=len(pool_codes),approved=len(cs),selection_note='轮换各行业候选并重新计算，复用未过期数据；行情与模型不变时可能出现相同结果。上涨大于下跌不等于上涨超过50%，也不保证盈利。')
    return out


def optimize(cs,budget,target_amount,mode,horizon,failed,policy,suitability_warning,risk_scale=1.):
    target=target_amount/budget
    dates=sorted(set.intersection(*[set(r['date'] for r in c['history']['rows']) for c in cs]))[-121:]
    if len(dates)<61:raise ValueError('对齐后的历史不足60日')
    closes=np.array([[{r['date']:r['close'] for r in c['history']['rows']}[d] for d in dates] for c in cs]).T
    returns=closes[1:]/closes[:-1]-1
    covariance=LedoitWolf().fit(returns).covariance_*252
    signal=np.array([c['long_prediction']['estimated_return'] if horizon=='long' else c['prediction']['up']-c['prediction']['down']-.5*c['prediction']['lower'] for c in cs])
    sector_cap=.30 if mode=='stable' else .40
    risk=(12. if mode=='stable' else 4.)*risk_scale*(1+max(0,target-policy['equity_cap']))
    sectors=sorted(set(c['quote']['industry'] for c in cs))
    # Concentration targets are soft penalties: small accounts may afford only one lot.
    cons=[{'type':'eq','fun':lambda w:np.sum(w)-target}]
    def objective(w):
        concentration=sum(max(0,sum(w[i] for i,c in enumerate(cs) if c['quote']['industry']==sector)-sector_cap)**2 for sector in sectors)
        return risk*float(w@covariance@w)-.08*float(signal@w)+2*float(np.square(np.maximum(w-.25,0)).sum())+2*concentration
    result=minimize(objective,np.full(len(cs),target/len(cs)),method='SLSQP',bounds=[(0,target)]*len(cs),constraints=cons,options={'maxiter':500,'ftol':1e-10})
    if not result.success:raise ValueError('本次组合计算未收敛，请刷新数据后重试')
    weights=np.maximum(result.x,0)
    rows,cash=fill_lots(cs,weights,budget,target_amount)
    actual=np.array([next((r['weight'] for r in rows if r['code']==c['code']),0) for c in cs])
    method=suitability_warning+'；'+('60交易日模型验证通过且收益估计为正；' if horizon=='long' else '5交易日模型；')+'先优化风险与分散目标，再补配整手余款；25%个股、行业30%/40%为软目标，小额预算可能超过。'
    return summarize(rows,budget,target_amount,mode,horizon,failed,policy,method,float(np.sqrt(actual@covariance@actual)))


def fill_lots(cs,weights,budget,target_amount):
    desired=np.array(weights)*budget;cost=np.array([round(c['quote']['price']*100,2)+math.ceil(c['quote']['price']*10)/100 for c in cs]);lots=np.floor(desired/cost).astype(int)
    remaining=target_amount-float(lots@cost)
    # Each extra lot approaches the requested investment amount; retain the closest weight fit.
    while True:
        eligible=np.where(cost<=remaining+1e-8)[0]
        if not len(eligible):break
        delta=2*(lots[eligible]*cost[eligible]-desired[eligible])*cost[eligible]+cost[eligible]**2
        i=int(eligible[np.argmin(delta)]);lots[i]+=1;remaining-=cost[i]
    quantities=[int(n)*100 for n in lots]
    rows=quantity_rows(cs,quantities,budget)
    return rows,round(budget-sum(r['amount']+r['fee'] for r in rows),2)


def quantity_rows(cs,quantities,budget):
    out=[]
    for c,n in zip(cs,quantities):
        if not n:continue
        q=c['quote'];amount=round(n*q['price'],2)
        out.append({'code':c['code'],'name':q['name'],'industry':q['industry'],'price':q['price'],'quantity':n,'amount':amount,'fee':round(amount*.001,2),'weight':amount/budget,'quote_time':q['quote_time'],**({'prediction':c['prediction'],'eligibility':c['eligibility'],'long_prediction':c.get('long_prediction')} if 'eligibility' in c else {})})
    return out


def summarize(rows,budget,target_amount,mode,horizon,failed,policy,method,volatility):
    spent=round(sum(r['amount']+r['fee'] for r in rows),2)
    if spent>budget+.01 or spent>target_amount+.05:raise ValueError('配置超过投入预算，请重新计算')
    return {'mode':mode,'horizon':horizon,'budget':budget,'target_amount':target_amount,'spent':spent,'uninvested_target':round(target_amount-spent,2),'positions':rows,'cash':round(budget-spent,2),'cash_pct':(budget-spent)/budget,'annualized_volatility':volatility,'limits':{'single_stock':.25,'industry':.30 if mode=='stable' else .40,'minimum_cash':1-target_amount/budget},'failed':failed,'asof':stamp(),'model_version':rows[0]['prediction']['version'] if rows and 'prediction' in rows[0] else models.info()['version'],'profile':policy,'method':method,'warning':'画像比例与分散比例为研究参考；手动方案可能超出风险承受能力。只对通过咨询复核的候选补配整手；没有合格股票时保留现金。买入费暂估0.1%，真实交易还需复核佣金及交易权限。软件不下单。'}


def manual(budget,positions):
    budget=float(budget)
    if not math.isfinite(budget) or not 500<budget<=1e9:raise ValueError('总资金需大于500元且不超过10亿元')
    if not isinstance(positions,list) or len(positions)>60:raise ValueError('持仓列表无效')
    cs=[];quantities=[];seen=set()
    for p in positions:
        code=market.symbol(p['code'])[2:];n=float(p['quantity'])
        if code in seen or not math.isfinite(n) or n<0 or n%100 or n>100_000_000:raise ValueError('代码不可重复，股数必须为非负100股整手')
        seen.add(code)
        if n==0:continue
        q=market.quote(code)
        if q['stale']:raise ValueError(code+'报价过期，请刷新后核对')
        cs.append({'code':code,'quote':q});quantities.append(int(n))
    rows=quantity_rows(cs,quantities,budget);spent=round(sum(r['amount']+r['fee'] for r in rows),2)
    if spent>budget:raise ValueError('调整后的股票金额及估计费用超过总预算')
    return {'positions':rows,'spent':spent,'cash':round(budget-spent,2),'budget':budget,'asof':stamp(),'note':'手动草案已核对最新报价和预算，仅保存到本地，不改变真实持仓、不执行交易。'}
