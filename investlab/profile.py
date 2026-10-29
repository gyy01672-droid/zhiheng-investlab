"""Transparent educational suitability assessment, not a bank certification."""
from datetime import datetime,timedelta
from . import store
from .config import stamp,now
QUESTIONS=[
('experience','投资经验','没有证券投资经验|不足1年|1至3年|超过3年'),
('knowledge','对股票损失与波动的理解','不了解|知道可能亏损|理解分散与波动|理解估值、回撤与流动性'),
('income','日常收入稳定程度','无稳定收入|收入波动较大|较稳定|稳定且来源多样'),
('reserve','应急资金可覆盖多久生活支出','不足1个月|1至3个月|3至6个月|超过6个月'),
('debt','债务偿还对收入的占用','超过50%|30%至50%|不足30%|无负债'),
('allocation','拟投资金额占可投资金融资产比例','超过75%|50%至75%|25%至50%|不足25%'),
('liquidity','这笔资金最早何时可能需要使用','1个月内|1至3个月|3至12个月|1年以上'),
('loss','可接受的本金损失幅度','不能接受损失|最多5%|最多15%|可接受超过15%'),
('reaction','组合短期下跌10%时的反应','无法承受需立即退出|明显焦虑并减仓|先核对原因|有预案且可承担继续波动'),
('goal','主要资金目标','保留本金与日常备用|追求较低波动|平衡风险与增长|承担较高风险追求增长')]
SOURCES=[{'title':'工商银行公开风险承受能力测试表','url':'https://www.icbc.com.cn/SiteCollectionDocuments/ICBC/Resources/ICBC/个人金融/下载/2010/131_135附录.pdf'}, {'title':'中国银行个人客户风险测评说明','url':'https://pic.bankofchina.com/bocappd/wealth/cs82/202603/P020260327646673351867.pdf'}]
def assess(answers):
    if set(answers)!=set(q[0] for q in QUESTIONS):raise ValueError('请完成全部10道题')
    if any(type(v) is not int or v not in range(4) for v in answers.values()):raise ValueError('问卷选项无效')
    score=sum(answers.values());level=min(5,score//6+1);reasons=[]
    if answers['loss']==0 or answers['liquidity']==0 or answers['reserve']==0:level=1;reasons.append('不能接受本金损失、近期用款或应急储备不足，股票配置上限降为零')
    if answers['experience']==0 and level>2:level=2;reasons.append('无证券经验，课程规则将等级上限设为谨慎型')
    cap=[0,.15,.35,.55,.75][level-1]
    return {'version':1,'score':score,'level':level,'label':['保守','谨慎','平衡','成长','进取'][level-1],'equity_cap':cap,'reasons':reasons,'answers':answers,'assessed_at':stamp(),'expires_at':(now()+timedelta(days=365)).isoformat(),'notice':'参考公开问卷维度自行设计评分；未经心理测量验证，不是银行或券商正式测评。'}
def current():
    p=store.get_setting('risk_profile')
    if p:
        guidance=['优先核对现金储备与存款期限，当前不配置股票。','先学习分散与成本，可比较存款及低波动产品的期限、费用和本金风险。','可研究现金储备与跨行业股票组合，定期检查集中度。','可研究分散股票组合与分批配置，保留应急资金并复核估值。','可研究成长行业的分散配置，但不使用杠杆，单一科技行业仍受集中度约束。'][p['level']-1]
        p=dict(p,expired=datetime.fromisoformat(p['expires_at'])<now(),guidance=guidance+'这是产品类别与策略教育，具体产品还需查阅说明书和正式适当性评估。')
    return p
def policy(horizon='short'):
    if horizon not in ['short','long']:raise ValueError('请选择短线或长线')
    p=current()
    if not p or p['expired']:return {'equity_cap':0,'message':'请完成或更新风险评估后生成个性化配置；仍可查看公开市场研究。','profile':p}
    cap=p['equity_cap'];message=p['label']+'画像，股票参考比例'+str(round(cap*100))+'%'
    if horizon=='long' and p['answers']['liquidity']<2:cap=0;message+='；用款期限短于60交易日，不匹配季度持有'
    return {'equity_cap':cap,'message':message,'profile':p}
def save(data):
    if data.get('acknowledged') is not True:raise ValueError('请阅读并确认研究用途与风险说明')
    p=assess(data.get('answers',{}));store.setting('risk_profile',p);store.setting('risk_disclosure',{'version':1,'time':stamp()});store.setting('profile_history',(store.get_setting('profile_history',[])+[p])[-50:]);return p

def allocation_defaults(horizon='short'):
    rule=policy(horizon);p=rule['profile']
    return {'mode':'aggressive' if p and not p['expired'] and p['level']>=4 else 'stable',
            'equity_ratio':rule['equity_cap'],'profile_label':p['label'] if p else '未评估',
            'valid':bool(p and not p['expired']),'message':rule['message'],
            'assessed_at':p['assessed_at'] if p else None}
