"""Single factual pipeline shared by consultation and all suggested securities."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import math
from . import market,models,horizons,profile,updates,alerts
from .config import now,CN,stamp

def quantitative(code,horizon='short',meta=None):
    profile.policy(horizon)
    code=market.symbol(code)[2:];meta=meta or models.info()
    with ThreadPoolExecutor(max_workers=2) as pool:
        q=pool.submit(market.quote,code);h=pool.submit(market.history,code)
        q=q.result()
        try:
            h=h.result()
            if h['adjustment']!='qfq':raise ValueError('当前历史不是前复权口径')
            p=models.predict(code,h,meta);lp=horizons.predict(h,meta) if horizon=='long' and p['available'] else None
        except Exception as e:h={'rows':[],'adjustment':None};p={'available':False,'message':str(e)};lp=None
    return {'code':code,'quote':q,'history':h,'prediction':p,'horizon':horizon,'long_prediction':lp}

def signal_rejection(c):
    p=c['prediction']
    if c['quote']['stale']:return '报价过期'
    if not p.get('available'):return p.get('message','判断模型不可用')
    if not all(math.isfinite(p[k]) and 0<=p[k]<=1 for k in ['up','flat','down','lower']):return '模型概率无效'
    if abs(sum(p[k] for k in ['up','flat','down'])-1)>1e-5:return '方向概率合计异常'
    if p['up']<=p['down']:return '上涨估计概率未严格高于下跌估计概率'
    if not p.get('direction_beats_baseline'):return '方向模型未优于多数类基线'
    if p['lower']>=.5:return '未来5日下探风险估计不低于50%'
    if c['horizon']=='long':
        lp=c.get('long_prediction')
        if not lp or not lp.get('available'):return '长期模型不可用'
        if not lp['beats_baseline'] or lp['estimated_return']<=0:return '长期收益信号未通过独立基线与正收益条件'
    return None

def consultation(code,horizon='short',snapshot=None):
    c=snapshot or quantitative(code,horizon);code=c['code'];updates.remember(code)
    ev=market.evidence(code);updates.save_knowledge(code,ev)
    reports=[i for i in ev['items'] if i['official'] and any(w in i['title'] for w in ['年度报告','半年度报告','季度报告']) and '摘要' not in i['title']]
    report=None
    if reports:
        try:report=market.announcement_content(reports[0]['id'])
        except Exception as e:ev['errors'].append('财报正文：'+str(e))
    flags=[]
    for item in ev['items']:
        try:
            dt=datetime.fromisoformat(item['published_at'].replace('Z','+00:00'))
            if dt.tzinfo is None:dt=dt.replace(tzinfo=CN)
            if not now()-timedelta(hours=72)<=dt<=now()+timedelta(hours=1):continue
        except (ValueError,KeyError):continue
        verdict=alerts.classify(item)
        if verdict and verdict['level']=='重点核查':flags.append(item['title'])
    reason=signal_rejection(c)
    if reason is None and flags:reason='近期公告含待核实风险关键词：'+'；'.join(flags[:2])
    if reason is None and not ev['items'] and ev['errors']:reason='公开证据读取失败，不能完成咨询复核'
    suitability=profile.policy(horizon)
    decision=('通过研究候选筛选，仍需独立核实，不构成买入指令' if reason is None else '暂不列入推荐：'+reason)
    if suitability['equity_cap']==0:decision+='；当前画像不匹配股票配置'
    c.update(evidence=ev,financial_report=report,suitability=suitability,decision=decision,
             eligibility={'passed':reason is None,'reason':reason,'reviewed_at':stamp(),'risk_flags':flags,
                          'financial_report_available':bool(report),'source_errors':ev['errors'],
                          'note':'通过仅表示满足研究筛选规则；公告关键词不等同事实认定，无资讯也不等同没有风险。'})
    return c
