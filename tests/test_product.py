import pytest
from investlab import store,updates,market

def trade(side='BUY',price='10',qty=100,day='2025-01-02',fee='5'):
    return dict(code='600900',name='测试',side=side,price=price,quantity=qty,date=day+'T10:00',fee=fee,confirmed=True)

@pytest.fixture(autouse=True)
def clean():
    store.init()
    with store.db() as c:c.execute('DELETE FROM trades')

def test_partial_sell_and_closed_realized():
    store.add_trade(trade(qty=200))
    store.add_trade(trade('SELL','12',100,'2025-01-03'))
    b=store.ledger(store.trades())['books'][0]
    assert b['cost']==1002.5 and b['realized']==192.5
    store.add_trade(trade('SELL','11',100,'2025-01-06'))
    b=store.ledger(store.trades())['books'][0]
    assert b['quantity']==0 and b['cost']==0 and b['realized']==285
    assert store.open_codes()==[]

def test_reject_oversell_same_day_and_void_dependency():
    uid=store.add_trade(trade())
    with pytest.raises(ValueError):store.add_trade(trade('SELL','11',101,'2025-01-03'))
    with pytest.raises(ValueError):store.add_trade(trade('SELL','11',100,'2025-01-02'))
    sell=store.add_trade(trade('SELL','11',100,'2025-01-03'))
    with pytest.raises(ValueError):store.void_trade(uid)
    store.void_trade(sell);store.void_trade(uid)
    assert not store.trades()

def test_backdated_sale_validates_whole_path():
    store.add_trade(trade())
    store.add_trade(trade('SELL','11',100,'2025-01-06'))
    with pytest.raises(ValueError):store.add_trade(trade('SELL','12',100,'2025-01-03'))
    assert len(store.trades())==2

def test_gate_requires_coverage_and_fresh_forward_dates(monkeypatch,tmp_path):
    import json
    monkeypatch.setattr(updates,"STATE",tmp_path)
    (tmp_path/"models").mkdir()
    (tmp_path/"models/long.json").write_text(json.dumps({k:{"mae":.1,"baseline_mae":.2} for k in ["test","unseen"]}))
    monkeypatch.setattr(updates.models,'info',lambda:{'schema_version':2,'splits':{'test':{'end':'2025-01-01'}}})
    c={'industry_coverage':{'工业':{'train':['a','b','c']}},'unseen_metrics':{'samples':600,'lower_brier':.1,'baseline_brier':.2,'macro_f1':.4,'majority_f1':.2}}
    assert not updates.promotion_check(c)['eligible']
    c['evaluation_dates']=['2025-02-'+str(i).zfill(2) for i in range(1,21)]
    assert updates.promotion_check(c)['eligible']
    c['industry_coverage']={}
    assert not updates.promotion_check(c)['eligible']

def test_reference_uses_exact_unadjusted_date(monkeypatch):
    monkeypatch.setattr(market,'cached',lambda k,t,fn:fn())
    monkeypatch.setattr(market,'fetch',lambda u:'{"data":{"sh600900":{"day":[["2025-01-02","10","11","12","9","100"]]}}}')
    r=market.trade_reference('600900','2025-01-02T10:30')
    assert r['price']==11 and r['adjustment']=='raw' and r['confirmed'] is False
    with pytest.raises(market.DataError):market.trade_reference('600900','2025-01-04')
