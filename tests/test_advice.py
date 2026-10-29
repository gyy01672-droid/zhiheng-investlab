import copy
import pytest
from investlab import advice,portfolio,models,market,profile,store
from investlab.config import stamp

def snapshot(up=.55,down=.25,lower=.2,horizon='short'):
    return {'code':'600900','quote':{'stale':False},'prediction':{'available':True,'up':up,'down':down,'flat':1-up-down,'lower':lower,'direction_beats_baseline':True},'horizon':horizon}

@pytest.mark.parametrize('up,down',[(.3,.4),(.4,.4)])
def test_no_negative_or_tied_direction_can_be_recommended(up,down):
    assert advice.signal_rejection(snapshot(up,down))

def test_positive_comparison_is_not_a_majority_probability():
    assert advice.signal_rejection(snapshot(.35,.3)) is None
    assert advice.signal_rejection(snapshot(lower=.5))
    assert advice.signal_rejection(snapshot(horizon='long'))

def test_full_consultation_blocks_recent_official_risk(monkeypatch):
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[{'title':'公司被立案调查','official':True,'published_at':stamp()}],'errors':[]})
    c=advice.consultation('600900',snapshot=snapshot())
    assert not c['eligibility']['passed'] and c['eligibility']['risk_flags']
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[{'title':'公司澄清不存在财务造假','official':True,'published_at':stamp()}],'errors':[]})
    assert advice.consultation('600900',snapshot=snapshot())['eligibility']['passed']

def test_empty_failed_evidence_cannot_pass(monkeypatch):
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[],'errors':['timeout']})
    assert not advice.consultation('600900',snapshot=snapshot())['eligibility']['passed']

def test_all_plans_and_singles_use_consultation_checks(monkeypatch):
    from datetime import date,timedelta
    codes=['60090'+str(i) for i in range(6)]
    monkeypatch.setattr(models,'info',lambda:{'version':'same-model','industry_coverage':{str(i):{'train':[c]} for i,c in enumerate(codes)}})
    def quant(code,horizon,meta):
        c=snapshot(.25,.6) if code==codes[0] else snapshot()
        c.update(code=code,history={'rows':[dict(date=str(date(2024,1,1)+timedelta(days=i)),close=10+i*.02) for i in range(125)]})
        c['quote'].update(price=5,name=code,industry=code,quote_time='snapshot')
        c['prediction'].update(version='same-model',asof='same-date')
        return c
    monkeypatch.setattr(advice,'quantitative',quant)
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[{'title':'收到处罚','official':True,'published_at':stamp()}] if c==codes[1] else [],'errors':[]})
    p=portfolio.allocate(10000,'aggressive',stock_budget=8500)
    plans=p['alternatives']+p['singles']
    assert plans and p['approved']==4
    signatures=[]
    for plan in plans:
        assert plan['spent']<=8500 and plan['positions']
        for r in plan['positions']:
            assert r['code'] not in codes[:2]
            assert r['eligibility']['passed']
            assert r['prediction']['up']>r['prediction']['down']
            assert r['prediction']['version']=='same-model'
        signatures.append(tuple((r['code'],r['quantity']) for r in plan['positions']))
    assert len(signatures)==len(set(signatures))

def test_profile_defaults_and_liquidity():
    answers={q[0]:3 for q in profile.QUESTIONS}
    profile.save({'answers':answers,'acknowledged':True})
    assert profile.allocation_defaults()['mode']=='aggressive'
    assert profile.allocation_defaults()['equity_ratio']==.75
    answers['liquidity']=1
    profile.save({'answers':answers,'acknowledged':True})
    assert profile.allocation_defaults('long')['equity_ratio']==0

def test_ledger_cash_amounts_are_not_only_price():
    base={'code':'600900','price':'10.25','quantity':200,'fee':'5','confirmed':True}
    store.add_trade(dict(base,side='BUY',date='2025-01-02'))
    store.add_trade(dict(base,side='SELL',price='11.25',date='2025-01-03'))
    buy,sell=store.ledger(store.trades())['trades']
    assert buy['amount']==2050 and buy['net_cash']==-2055
    assert sell['amount']==2250 and sell['net_cash']==2245
    assert sell['realized_pnl']==190
