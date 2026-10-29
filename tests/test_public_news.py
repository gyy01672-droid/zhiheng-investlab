import json
import pytest
from investlab import public_news,market

def payload(ext=None):
    return {'result':{'status':{'code':0},'data':{'feed':{'list':[{'id':1,'rich_text':'【测试公司：收到处罚】<b>详情需核实</b>','create_time':'2026-10-29 16:00:00','ext':json.dumps(ext or {'stocks':[{'market':'cn','symbol':'sh600900'}]})}]}}}}

def test_public_feed_time_and_stock_matching():
    item=public_news.parse_feed(payload(),'2026-10-29T16:01:00+08:00')[0]
    assert item['published_at'].endswith('+08:00') and '<b>' not in item['content']
    assert item['fetched_at']=='2026-10-29T16:01:00+08:00' and not item['official']
    assert public_news.matches(item,'600900','测试公司')
    assert not public_news.matches(item,'600901','测试公司')

def test_company_does_not_match_tagged_hk_subsidiary():
    item=public_news.parse_feed(payload({'stocks':[{'market':'hk','symbol':'00285'}]}),'now')[0]
    item['title']='比亚迪电子亏损'
    assert not public_news.matches(item,'002594','比亚迪')

def test_invalid_feed_is_failure_not_empty_success():
    with pytest.raises(market.DataError):public_news.parse_feed({},'now')
    p=payload();p['result']['data']['feed']['list']=[]
    with pytest.raises(market.DataError):public_news.parse_feed(p,'now')

def test_news_failure_does_not_remove_announcements(monkeypatch):
    monkeypatch.setattr(market,'quote',lambda c:{'name':'测试公司'})
    monkeypatch.setattr(market,'announcements',lambda c:[{'title':'公告','published_at':'2026-10-29','official':True}])
    monkeypatch.setattr(market,'news',lambda n:[])
    def fail(*a):raise market.DataError('来源故障')
    monkeypatch.setattr(public_news,'company',fail)
    r=market.evidence('600900')
    assert r['items'][0]['title']=='公告' and r['errors']
    assert 'weibo' not in r and '新浪' in r['coverage']
