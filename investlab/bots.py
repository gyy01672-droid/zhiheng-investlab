"""Opt-in outbound notifications; credentials are Windows-user DPAPI encrypted."""
import json,re,time,threading,urllib.request,urllib.error,ctypes
from ctypes import wintypes
from . import store
from .config import STATE,stamp
LOCK=threading.RLock()
class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
def protect(raw,decrypt=False):
    buf=ctypes.create_string_buffer(raw);src=Blob(len(raw),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));dst=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    fn=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not fn(ctypes.byref(src),None,None,None,None,1,ctypes.byref(dst)):raise ValueError('本机凭据加密服务不可用')
    try:return ctypes.string_at(dst.data,dst.size)
    finally:kernel.LocalFree(ctypes.cast(dst.data,ctypes.c_void_p))
def credentials():
    p=STATE/'bot.key'
    return json.loads(protect(p.read_bytes(),True)) if p.exists() else {}
def status():
    cfg=store.get_setting('bot_config',{'enabled':False,'provider':'telegram','interval_minutes':0})
    state=store.get_setting('bot_delivery',{})
    return dict(cfg,configured=(STATE/'bot.key').exists(),deliveries=[{k:v for k,v in r.items() if k!='text'} for r in list(state.values())[-30:]],note='只发事件标题、代码、来源与时间；不发持仓金额或问卷。程序和网络须保持可用。')
def save(data):
    with LOCK:
        enabled=data.get('enabled')
        if type(enabled) is not bool:raise ValueError('开关格式无效')
        if enabled and data.get('acknowledged') is not True:raise ValueError('请确认允许向所配置账号发送事件信息')
        provider=data.get('provider');interval=int(data.get('interval_minutes',0))
        if provider not in ['telegram','wecom'] or interval not in [0,60,240,1440]:raise ValueError('通知设置无效')
        old=credentials();secret=str(data.get('secret','')).strip() or (old.get('secret','') if old.get('provider')==provider else '')
        recipient=str(data.get('recipient','')).strip() or (old.get('recipient','') if old.get('provider')==provider else '')
        if provider=='telegram':
            valid=bool(re.fullmatch(r'\d{5,16}:[A-Za-z0-9_-]{20,100}',secret) and re.fullmatch(r'-?\d{1,20}',recipient))
        else:
            if secret.startswith('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='):secret=secret.split('key=',1)[1]
            valid=bool(re.fullmatch(r'[a-zA-Z0-9_-]{16,100}',secret))
        if enabled and not valid:raise ValueError('请填写有效的机器人凭据与接收人')
        if valid:
            p=STATE/'bot.key';tmp=p.with_suffix('.tmp');tmp.write_bytes(protect(json.dumps(dict(provider=provider,secret=secret,recipient=recipient)).encode()));tmp.replace(p)
        cfg=dict(enabled=enabled,provider=provider,interval_minutes=interval,activated_at=stamp(),next_summary=time.time()+interval*60,recipient_hint=('尾号'+recipient[-4:]) if provider=='telegram' and recipient else '企业微信群')
        store.setting('bot_config',cfg);store.setting('bot_delivery',{});return status()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('通知接口发生重定向，已拒绝发送')
def send(text):
    c=credentials();provider=c.get('provider')
    if provider=='telegram':url='https://api.telegram.org/bot'+c['secret']+'/sendMessage';payload={'chat_id':c['recipient'],'text':text[:2000],'link_preview_options':{'is_disabled':True}}
    elif provider=='wecom':url='https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key='+c['secret'];payload={'msgtype':'text','text':{'content':text.encode('utf-8')[:1800].decode('utf-8',errors='ignore')}}
    else:raise ValueError('尚未配置机器人')
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=15) as r:reply=json.loads(r.read(100000))
        ok=reply.get('ok') is True if provider=='telegram' else reply.get('errcode')==0
        if not ok:raise ValueError('服务端未接受消息，请检查凭据、接收人或额度')
    except urllib.error.HTTPError as e:raise ValueError('通知请求失败，HTTP '+str(e.code)) from None
    except ValueError:raise
    except Exception:raise ValueError('通知网络不可用或超时；超时重试可能造成重复消息') from None

def tick(test=False,retry=False):
    with LOCK:
        cfg=store.get_setting('bot_config',{})
        if not cfg.get('enabled'):
            if test:raise ValueError('请先保存并开启通知')
            return status()
        pending=store.get_setting('bot_delivery',{});now=time.time()
        if retry:
            for r in pending.values():
                if r['status']=='failed':r.update(attempts=0,next_try=0,status='pending')
        events=store.events()
        for e in events['events']:
            if e['created_at']<cfg['activated_at'] or e['id'] in pending:continue
            text='知衡风险提醒（请核实，不是抛售指令）\n'+e['code']+' '+e['title']+'\n发布：'+e['published_at']+'\n来源：'+e['payload'].get('source','未知')+'\n'+e['payload'].get('url','')
            pending[e['id']]={'text':text,'status':'pending','attempts':0,'next_try':0,'created_at':stamp()}
        key='test-'+str(time.time_ns())
        if test:pending[key]={'text':'知衡连接测试：此消息不包含持仓和问卷数据。','status':'pending','attempts':0,'next_try':0,'created_at':stamp()}
        if cfg['interval_minutes'] and now>=cfg['next_summary']:
            pending['summary-'+str(int(now))]={'text':'知衡定时巡检摘要\n时间：'+stamp()+'\n最新巡检状态：'+(events['scans'][0]['status']+'（'+events['scans'][0]['started_at']+'）' if events['scans'] else '尚无巡检记录')+'\n没有发现事件不代表没有风险。','status':'pending','attempts':0,'next_try':0,'created_at':stamp()}
            cfg['next_summary']=now+cfg['interval_minutes']*60;store.setting('bot_config',cfg)
        # Prioritize explicit connection tests; limit traffic to three messages per tick.
        work=list(pending.items());work.sort(key=lambda x:x[0]!=key)
        for _,r in [x for x in work if x[1]['status']=='pending' and x[1]['next_try']<=now][:3]:
            r['attempts']+=1
            try:send(r['text']);r.update(status='sent',sent_at=stamp(),error=None)
            except Exception as e:r.update(status='failed' if r['attempts']>=5 else 'pending',error=str(e),next_try=now+min(3600,30*2**r['attempts']))
        store.setting('bot_delivery',dict(list(pending.items())[-1000:]));return status()
