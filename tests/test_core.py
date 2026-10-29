import os,tempfile,math,json
from pathlib import Path
import numpy as np
import pytest
from investlab import market,models,store,alerts,portfolio
from investlab.config import STATE

@pytest.fixture(autouse=True)
def database():
    store.init()
    with store.db() as c:
        for table in ['lots','trades','events','settings','scans']:c.execute('DELETE FROM '+table)

def rows(n=140):
    from datetime import date,timedelta
    return [dict(date=(date(2024,1,1)+timedelta(days=i)).isoformat(),open=10+i*.02,close=10+i*.02+.01,high=10+i*.02+.1,low=10+i*.02-.1,volume=100+i) for i in range(n)]

def test_future_prices_cannot_change_features():
    original=rows();changed=rows()
    for i,r in enumerate(changed[126:]):
        for k in ['open','close','high','low']:r[k]*=(2+i*.1)
    a=models.features(original);b=models.features(changed)
    assert np.allclose(a[5]['x'],b[5]['x'])
    assert a[5]['r']!=b[5]['r']
    assert 'y' not in a[-1]

def test_target_enters_next_open_and_cost():
    r=rows();r[121]['open']=15;r[125]['close']=18
    f=models.features(r)[0]
    assert f['r']==pytest.approx(.198)
    assert f['end']==r[125]['date']

@pytest.mark.parametrize('code',['../../secrets','abc','123','888888','600519?x=1'])
def test_invalid_symbol(code):
    with pytest.raises(ValueError):market.symbol(code)

def test_decimal_pnl_and_aggregation():
    lots=[dict(price='10.10',quantity=100,fee='5.00'),dict(price='10.20',quantity=200,fee='5')]
    p=store.mark_pnl(lots,10.30)
    assert p['cost']==3060
    assert p['pnl']==30
    assert p['quantity']==300

@pytest.mark.parametrize('field,value',[('price','NaN'),('price','-1'),('fee','-1'),('quantity','1.5'),('quantity','0'),('date','2999-01-01')])
def test_bad_holding_rejected(field,value):
    d=dict(code='600519',price='10',quantity='100',fee='5',date='2025-01-01');d[field]=value
    with pytest.raises(Exception):store.add_lot(d)
    assert store.lots()==[]

def test_event_dedup_and_denial():
    event=dict(title='公司澄清：不存在财务造假',published_at='2026-10-28',official=True)
    assert alerts.classify(event)['level']=='待核实'
    assert store.save_event('600519',event,'待核实')
    assert not store.save_event('600519',event,'待核实')
    assert len(store.events()['events'])==1

def test_rounding_respects_cash_and_caps():
    cs=[dict(code=str(i),quote=dict(name='test',price=9.99+i*2,industry='test',quote_time='2026-10-28')) for i in range(4)]
    r,cash=portfolio.round_positions(cs,[.2,.15,.15,.15],100000)
    assert all(p['quantity']%100==0 for p in r)
    assert all(p['weight']<=.25 for p in r)
    assert cash>=35000
    assert sum(p['amount']+p['fee'] for p in r)+cash==pytest.approx(100000)

def test_version_path_rejected():
    with pytest.raises(ValueError):models.activate('../../etc')

def test_allocation_solves_constraints(monkeypatch):
    monkeypatch.setattr(models,'info',lambda:{'version':'test'})
    monkeypatch.setattr(models,'predict',lambda *a:{'available':True,'up':.4,'flat':.3,'down':.3,'lower':.3,'direction_beats_baseline':True,'version':'test'})
    monkeypatch.setattr(market,'history',lambda c:{'rows':rows(),'adjustment':'qfq'})
    monkeypatch.setattr(market,'quote',lambda c:{'price':10,'name':c,'industry':portfolio.UNIVERSE[c][1],'quote_time':'2026-10-28','stale':False})
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[],'errors':[],'coverage':'test'})
    p=portfolio.allocate(100000,'stable')
    assert p['cash']>=34900  # cash target is before estimated buying fees
    assert all(x['quantity']%100==0 for x in p['positions'])
    assert p['spent']<=65000 and p['uninvested_target']<1001


def test_stale_market_excluded(monkeypatch):
    monkeypatch.setattr(portfolio.profile,'policy',lambda h:{'equity_cap':.65,'message':'test'})
    monkeypatch.setattr(models,'info',lambda:{'version':'test'})
    monkeypatch.setattr(market,'quote',lambda c:{'stale':True})
    monkeypatch.setattr(market,'history',lambda c:{'rows':rows(),'adjustment':'qfq'})
    result=portfolio.allocate(100000,'stable')
    assert not result['positions'] and result['cash']==100000

def test_scan_deduplicates_recent_events_and_records_failures(monkeypatch):
    from investlab.config import stamp
    store.add_lot(dict(code='600519',price='10',quantity=100,date='2025-01-01'))
    recent={'title':'公司收到立案通知','published_at':stamp(),'official':True}
    old={'title':'旧闻：重大诉讼','published_at':'2020-01-01','official':True}
    monkeypatch.setattr(market,'evidence',lambda c:{'items':[recent,old],'errors':['新闻暂不可用']})
    a=alerts.scan();b=alerts.scan()
    assert a['new_events']==1 and b['new_events']==0
    data=store.events()
    assert len(data['events'])==1 and data['scans'][0]['status']=='部分失败'

def test_http_origin_and_bad_input(monkeypatch):
    import app,threading,urllib.request,urllib.error
    server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
    monkeypatch.setattr(app,'PORT',server.server_port)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    try:
        request=urllib.request.Request(url+'/api/settings',data=b'{"monitor":true}',headers={'Content-Type':'application/json','X-InvestLab':'local','Origin':'https://untrusted.example'})
        with pytest.raises(urllib.error.HTTPError) as err:urllib.request.urlopen(request)
        assert err.value.code==403 and not store.get_setting('monitor',False)
        with pytest.raises(urllib.error.HTTPError) as err:urllib.request.urlopen(url+'/api/consult?code=invalid')
        assert err.value.code==400
        with urllib.request.urlopen(url+'/') as r:assert b'INVESTLAB' in r.read()
    finally:server.shutdown();server.server_close()

def test_llm_filters_wrong_probability_and_unsupported_missing_report():
    from investlab.llm import filter_explanation
    text='风险概率为3.49%。股价为一千三百元。财报未披露收入。未来五日下探至少三的概率。仍需核实公司公告与新闻原文。[E1]市场存在波动风险。[E9]'
    cleaned,n=filter_explanation(text,{'evidence':[{'ref':'E1'}],'financial_report':{'text':'局部摘录'}})
    assert '3.49' not in cleaned and '一千' not in cleaned and '未披露' not in cleaned and 'E9' not in cleaned and '概率' not in cleaned
    assert '仍需核实' in cleaned and n>=4
