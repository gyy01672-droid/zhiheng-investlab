import json,re,urllib.parse
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from . import market,models,store,profile,universe
from .config import stamp
LESSONS=[
{'title':'收益与风险','text':'高预期收益通常伴随更大的不确定性。历史收益不能保证未来收益，不能用借款或应急资金承担股票波动。','question':'历史盈利能保证未来盈利吗？','options':['不能','能'],'answer':0},
{'title':'分散与相关性','text':'买很多股票不一定分散风险，同一行业股票可能同时下跌。应同时观察单股、行业集中度和相关性，留足现金。','question':'同一行业的多只股票一定充分分散吗？','options':['是','否'],'answer':1},
{'title':'期限与流动性','text':'一个月后需要的钱不适合按季度持有假设配置。长期持有也不能消除公司经营和永久损失风险。','question':'长期持有是否完全没有损失风险？','options':['没有风险','仍有风险'],'answer':1},
{'title':'成本与复权','text':'复权价格用于比较历史收益，不能直接当作实际成交成本。记账应使用真实成交价和费用，并考虑分红送转。','question':'复权价能直接作为实际成交价吗？','options':['可以','不可以'],'answer':1},
{'title':'模型与传闻','text':'分类分数不是保证盈利的概率。未经核实的舆情应回到公告和原文检查，不能只凭关键词自动卖出。','question':'负面关键词命中后应如何处理？','options':['自动全卖','核实来源、日期及影响'],'answer':1}]
def quiz(answers):
    if not isinstance(answers,list) or len(answers)!=len(LESSONS) or any(type(x)is not int or x not in [0,1] for x in answers):raise ValueError('请完成全部教育题目')
    r={'score':sum(a==l['answer'] for a,l in zip(answers,LESSONS)),'total':len(LESSONS),'at':stamp(),'review':[{'title':l['title'],'correct':a==l['answer'],'explanation':l['text']} for a,l in zip(answers,LESSONS)]};store.setting('education_result',r);return r
def macro():
    from html.parser import HTMLParser
    base='https://www.stats.gov.cn/sj/zxfb/'
    class Links(HTMLParser):
        def __init__(self):super().__init__();self.items=[];self.href=None;self.words=[]
        def handle_starttag(self,t,a):
            if t=='a':self.href=dict(a).get('href');self.words=[]
        def handle_data(self,d):
            if self.href:self.words.append(d)
        def handle_endtag(self,t):
            if t=='a' and self.href:
                title=''.join(self.words).strip();url=urllib.parse.urljoin(base,self.href)
                if urllib.parse.urlparse(url).hostname=='www.stats.gov.cn' and any(k in title for k in ['居民消费','工业生产者','采购经理','国民经济','国内生产总值']):self.items.append({'title':title,'url':url,'source':'国家统计局','date':re.search(r'/t(\d{8})_',url).group(1) if re.search(r'/t(\d{8})_',url) else '见原文'})
                self.href=None
    p=Links();p.feed(market.fetch(base));items=list({x['url']:x for x in p.items}.values())[:10]
    if not items:raise ValueError('未解析到宏观发布，不能视为宏观风险为零')
    return items
def dashboard():
    def load():
        m=models.info();errors={};sectors=[]
        def one(pair):
            name,g=pair
            try:
                hs=[market.history(c)['rows'] for c in g['train'][:3]]
                r20=float(np.mean([h[-1]['close']/h[-21]['close']-1 for h in hs]));r60=float(np.mean([h[-1]['close']/h[-61]['close']-1 for h in hs]));return {'industry':name,'return20':r20,'return60':r60,'acceleration':r20-r60/3,'asof':min(h[-1]['date'] for h in hs),'codes':g['train'][:3]}
            except Exception as e:errors[name]=str(e)
        with ThreadPoolExecutor(4) as pool:sectors=[r for r in pool.map(one,m.get('industry_coverage',{}).items()) if r]
        sectors.sort(key=lambda x:x['return20'],reverse=True)
        try:items=macro()
        except Exception as e:
            errors['宏观官网']=str(e)
            try:items=[{'title':x['title'],'url':x['url'],'source':x['source'],'date':x['published_at']} for x in market.news('国家统计局')[:10]];errors['宏观说明']='官网读取失败，以下为财经新闻中的统计局报道，需核对原始发布；不作为已验证宏观数值'
            except Exception as ne:items=[];errors['宏观备用']=str(ne)
        return {'asof':stamp(),'sectors':sectors,'positive_industries':sum(r['return20']>0 for r in sectors),'macro':items,'errors':errors,'method':'每行业3只训练代表股等权近20/60日收益；轮动加速度为20日收益减60日收益的三分之一，不是全市场行业指数。','macro_analysis':['CPI/PPI：关注价格变化及企业成本与利润传导；不能单独推导股价。','PMI：观察景气扩张和收缩及行业差异。','GDP与国民经济：结合实际增速、结构与发布时间，避免把过去数据当作即时信号。']}
    return market.cached('market-dashboard:v1',900,load)

def rebalance(target):
    held={b['code']:b for b in store.ledger(store.trades())['books'] if b['quantity']>0};wanted={r['code']:r for r in target['positions']};rows=[]
    for code in sorted(set(held)|set(wanted)):
        current=held.get(code,{}).get('quantity',0);desired=wanted.get(code,{}).get('quantity',0)
        rows.append({'code':code,'current':current,'target':desired,'difference':desired-current,'sellable':held.get(code,{}).get('sellable_quantity',0)})
    return rows
def risk():
    books=[b for b in store.ledger(store.trades())['books'] if b['quantity']];out=[];errors={}
    for b in books:
        try:
            q=market.quote(b['code']);h=market.history(b['code'])['rows'];out.append(dict(b,value=q['price']*b['quantity'],industry=q['industry'],history=h,stale=q['stale']))
        except Exception as e:errors[b['code']]=str(e)
    if not out:return {'message':'暂无可分析持仓','positions':[],'errors':errors}
    total=sum(r['value'] for r in out);sector={};suggestions=[]
    for r in out:
        if r['stale']:errors[r['code']]='估值报价过期，权重与风险结果仅为近似，请刷新后复核'
        r['weight']=r['value']/total;sector[r['industry']]=sector.get(r['industry'],0)+r['weight']
        if r['weight']>.25:suggestions.append(r['code']+'占股票市值超过25%，可研究降低集中度')
    dates=sorted(set.intersection(*[{r['date'] for r in x['history']} for x in out]))[-121:]
    if len(dates)<61:raise ValueError('共同历史不足，不能计算组合风险')
    c=np.array([[{r['date']:r['close'] for r in x['history']}[d] for d in dates] for x in out]).T
    daily=(c[1:]/c[:-1]-1)@np.array([r['weight'] for r in out]);eq=np.cumprod(1+daily);dd=float(min(eq/np.maximum.accumulate(np.r_[1,eq])[1:]-1))
    for k,v in sector.items():
        if v>.4:suggestions.append(k+'超过股票市值40%，可研究跨行业分散')
    if profile.policy()['equity_cap']==0:suggestions.append('当前画像不匹配股票配置，请先核对画像、用款需求和现有持仓')
    return {'positions':[{k:v for k,v in r.items() if k!='history'} for r in out],'errors':errors,'volatility':float(np.std(daily)*np.sqrt(252)),'historical_var95':max(0,float(-np.quantile(daily,.05))),'drawdown':dd,'industry_weights':sector,'suggestions':suggestions or ['当前集中度未越过研究阈值，仍需持续检查'],'method':'按当前股票权重固定回放近120交易日，不是账户实际净值；不含账户现金。VaR不是最大损失保证。','asof':stamp()}
def backtest():
    m=models.info();b=m['backtest'];v=np.array([1.]+[r['strategy'] for r in b['curve']]);r=v[1:]/v[:-1]-1
    return dict(b,version=m['version'],period=m['splits']['test'],sharpe=float(np.mean(r)/np.std(r)*np.sqrt(252/5)) if np.std(r)>0 else None,win_rate=float(np.mean(r>0)) if len(r) else None,method='已保存独立测试区间的固定5日策略；夏普采用零无风险利率，胜率按回放周期计算；60日模型目前报告预测误差，不伪造长期策略回测。')
