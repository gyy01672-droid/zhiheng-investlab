import random
import pytest
from investlab import bots,exploration,store,universe

def test_exploration_does_not_touch_holdout_or_training(monkeypatch):
    monkeypatch.setattr(universe,'current',lambda:{'stocks':{str(c):{'name':'公司'} for c in range(600001,600030)}})
    meta={'training_symbols':['600001'],'heldout_symbols':['600002']}
    base=['600001','600030','600031']
    unchanged,info=exploration.select(base,meta,0,random.Random(1))
    assert unchanged==base and info['exploration_count']==0
    found,info=exploration.select(base,meta,.5,random.Random(1))
    assert len(found)==len(set(found))==len(base)
    assert info['explored_codes'] and not set(info['explored_codes'])&{'600001','600002'}
    with pytest.raises(ValueError):exploration.select(base,meta,float('nan'))

def test_bots_disabled_never_sends(monkeypatch):
    monkeypatch.setattr(bots,'send',lambda t:pytest.fail('disabled sent'))
    bots.tick()
    with pytest.raises(ValueError):bots.tick(test=True)

def test_notify_retry_redaction_and_dedup(monkeypatch):
    store.setting('bot_config',dict(enabled=True,provider='telegram',activated_at='2000',interval_minutes=0,next_summary=0))
    event={'id':'one','created_at':'2026','code':'600900','title':'待核实事件','published_at':'2026','payload':{'source':'测试','url':'https://example.org'}}
    monkeypatch.setattr(store,'events',lambda:{'events':[event],'scans':[]})
    calls=[]
    monkeypatch.setattr(bots,'send',lambda t:calls.append(t))
    bots.tick();bots.tick()
    assert len(calls)==1 and '金额' not in calls[0]
    assert bots.status()['deliveries'][0]['status']=='sent'
    assert 'text' not in bots.status()['deliveries'][0]

def test_retry_preserves_failed_message(monkeypatch):
    store.setting('bot_config',dict(enabled=True,provider='telegram',activated_at='2000',interval_minutes=0,next_summary=0))
    monkeypatch.setattr(bots,'send',lambda t:(_ for _ in ()).throw(ValueError('网络不可用')))
    r=bots.tick(test=True)
    assert r['deliveries'][0]['status']=='pending' and r['deliveries'][0]['attempts']==1
    bots.tick();assert bots.status()['deliveries'][0]['attempts']==1

def test_settings_consent_and_secret_not_echoed(monkeypatch):
    monkeypatch.setattr(bots,'credentials',lambda:{})
    with pytest.raises(ValueError):bots.save(dict(enabled=True,provider='telegram',interval_minutes=0))
    with pytest.raises(ValueError):bots.save(dict(enabled=True,acknowledged=True,provider='wecom',secret='https://evil.example/?key=x',interval_minutes=0))

def test_notification_transport_payload(monkeypatch):
    monkeypatch.setattr(bots,'credentials',lambda:{'provider':'telegram','secret':'test-token','recipient':'1234'})
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,n):return b'{"ok":true}'
    class Opener:
        def open(self,req,timeout):
            import json
            body=json.loads(req.data);assert body['chat_id']=='1234' and body['text']=='hello'
            assert req.full_url.startswith('https://api.telegram.org/')
            return Response()
    monkeypatch.setattr(bots.urllib.request,'build_opener',lambda *a:Opener())
    bots.send('hello')


def test_wecom_payload_and_server_error(monkeypatch):
    import json
    monkeypatch.setattr(bots,'credentials',lambda:{'provider':'wecom','secret':'test-key'})
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,n):return b'{"errcode":93000}'
    class Opener:
        def open(self,req,timeout):
            body=json.loads(req.data)
            assert body['msgtype']=='text' and len(body['text']['content'].encode())<=1800
            assert req.full_url.startswith('https://qyapi.weixin.qq.com/')
            return Response()
    monkeypatch.setattr(bots.urllib.request,'build_opener',lambda *a:Opener())
    with pytest.raises(ValueError,match='未接受'):bots.send('通知'*2000)
