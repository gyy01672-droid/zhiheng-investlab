"""Local, single-user investment research app. No broker connection or trading endpoint."""
import json,threading,traceback,urllib.parse,mimetypes,webbrowser,sys,os,socket
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
from investlab import market,models,llm,store,alerts,portfolio,universe,updates,public_news,profile,horizons,research
from investlab.config import ROOT,STATE,stamp

PORT=8765

class LocalServer(ThreadingHTTPServer):
    allow_reuse_address=False
    def server_bind(self):
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()

def financial_excerpt(report):
    """Select source passages, without inventing units or parsing financial ratios."""
    if not report:return None
    import re
    text=report['text'];pieces=[text[:350]]
    for word in ['主要会计数据','营业收入','归属于上市公司股东的净利润','经营活动产生的现金流量净额','风险']:
        match=re.search(word,text)
        if match:pieces.append(text[max(0,match.start()-80):match.start()+330])
    return {'title':report['title'],'id':report['id'],'text':'\n……\n'.join(pieces)[:2100],
            'note':'来源正文局部摘录；金额需连同原文单位核实。'}

from investlab.advice import consultation

def holding_snapshot():
    account=store.ledger(store.trades());positions=[];errors={}
    for book in account['books']:
        if book['quantity']==0:continue
        code=book['code']
        try:
            q=market.quote(code);value=q['price']*book['quantity'];pnl=value-book['cost']
            positions.append(dict(book,name=q['name'],quote=q,market_value=value,pnl=pnl,return_pct=pnl/book['cost']*100 if book['cost'] else 0))
        except Exception as e:errors[code]=str(e);positions.append(dict(book,quote=None,market_value=None,pnl=None,return_pct=None))
    realized=sum(b['realized'] for b in account['books']);floating=sum(p['pnl'] or 0 for p in positions)
    return {'positions':positions,'trades':account['trades'],'errors':errors,'complete':not errors,
            'confirmed':all(t['confirmed'] for t in account['trades']),
            'totals':{'cost':sum(p['cost'] for p in positions),'market_value':sum(p['market_value'] or 0 for p in positions),
                      'realized':realized,'unrealized':floating if not errors else None,'total_pnl':realized+floating if not errors else None,
                      'fees':sum(b['fees'] for b in account['books'])}}

def status():
    versions=[]
    if models.info() and models.STATUS['message']=='尚未训练':models.STATUS['message']='判断模型已就绪；可手动训练新候选'
    for p in sorted((STATE/'models').glob('*/manifest.json'),reverse=True):
        try:versions.append(json.loads(p.read_text(encoding='utf-8')))
        except (OSError,ValueError):pass
    return {'time':stamp(),'model':models.info(),'training':models.STATUS,'llm':llm.status(),'versions':versions,
            'monitor':store.get_setting('monitor',True),'selflearn':store.get_setting('selflearn',True),'alerts':alerts.STATE,
            'auto_data':store.get_setting('auto_data',True),'auto_promote':store.get_setting('auto_promote',True),
            'updates':updates.STATUS,'update_history':updates.history()[:5],'universe':universe.current(),
            'hardware':'CPU训练与CPU量化推理；NPU未启用','news_monitor':'公开公告、公司新闻与新浪财经快讯；每轮后120秒巡检'}

def background(fn):
    def run():
        try:fn()
        except Exception:traceback.print_exc()
    threading.Thread(target=run,daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def reply(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_GET(self):self.handle_request(False)
    def do_POST(self):self.handle_request(True)
    def handle_request(self,mutate):
        try:
            if self.headers.get('Host') not in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']:return self.reply({'error':'仅允许本机访问'},403)
            parsed=urllib.parse.urlparse(self.path);path=parsed.path;query=urllib.parse.parse_qs(parsed.query)
            if mutate:
                if self.headers.get('X-InvestLab')!='local' or self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply({'error':'请求校验失败'},403)
                origin=self.headers.get('Origin')
                if origin and origin not in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']:return self.reply({'error':'来源校验失败'},403)
                length=int(self.headers.get('Content-Length',0))
                if length>50000:return self.reply({'error':'输入过长'},413)
                data=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(data,dict):raise ValueError('输入格式错误')
            else:data={}
            if path=='/api/status' and not mutate:result=status()
            elif path=='/api/consult' and not mutate:result=consultation(query.get('code',[''])[0],query.get('horizon',['short'])[0])
            elif path=='/api/quote' and not mutate:result=market.quote(query.get('code',[''])[0])
            elif path=='/api/trade-reference' and not mutate:result=market.trade_reference(query.get('code',[''])[0],query.get('date',[''])[0])
            elif path=='/api/profile' and not mutate:result={'questions':[{'id':q[0],'title':q[1],'options':q[2].split('|')} for q in profile.QUESTIONS],'profile':profile.current(),'sources':profile.SOURCES}
            elif path=='/api/profile/allocation' and not mutate:result=profile.allocation_defaults(query.get('horizon',['short'])[0])
            elif path=='/api/profile' and mutate:result=profile.save(data)
            elif path=='/api/market' and not mutate:result=research.dashboard()
            elif path=='/api/risk' and not mutate:result=research.risk()
            elif path=='/api/backtest' and not mutate:result=research.backtest()
            elif path=='/api/education' and not mutate:result={'lessons':[{k:v for k,v in x.items() if k!='answer'} for x in research.LESSONS],'result':store.get_setting('education_result')}
            elif path=='/api/education' and mutate:result=research.quiz(data.get('answers'))
            elif path=='/api/holdings' and not mutate:result=holding_snapshot()
            elif path=='/api/events' and not mutate:result=store.events()
            elif path=='/api/announcement' and not mutate:result=market.announcement_content(query.get('id',[''])[0])
            elif path=='/api/explain' and mutate:
                c=consultation(data.get('code',''),data.get('horizon','short'))
                all_items=c['evidence']['items']
                selected=[i for i in all_items if i['official']][:2]+[i for i in all_items if not i['official']][:4]
                evidence=[dict(i,content=i.get('content','')[:220],ref=f'E{n+1}') for n,i in enumerate(selected)]
                report=c['financial_report']
                result=llm.explain({'horizon':c['horizon'],'suitability':c['suitability'],'long_prediction':c['long_prediction'],'quote':c['quote'],'prediction':c['prediction'],'decision':c['decision'],'evidence':evidence,
                                    'financial_report':financial_excerpt(report),
                                    'source_errors':c['evidence']['errors'],'coverage':c['evidence']['coverage']})
                result['evidence']=evidence
            elif path=='/api/holdings/add' and mutate:
                q=market.quote(data.get('code',''));data['name']=q['name'];result={'id':store.add_lot(data)}
            elif path=='/api/holdings/remove' and mutate:store.remove_lot(str(data.get('id','')));result={'ok':True}
            elif path=='/api/trades/add' and mutate:
                q=market.quote(data.get('code',''));data['name']=q['name'];result={'id':store.add_trade(data)};updates.remember(q['code'])
            elif path=='/api/trades/void' and mutate:store.void_trade(str(data.get('id','')));result={'ok':True}
            elif path=='/api/history' and not mutate:result=market.history(query.get('code',[''])[0])
            elif path=='/api/portfolio/manual' and not mutate:result=store.get_setting('manual_portfolio',{})
            elif path=='/api/portfolio/manual' and mutate:
                result=portfolio.manual(data.get('budget',0),data.get('positions',[]));store.setting('manual_portfolio',result)
            elif path=='/api/portfolio' and mutate:
                result=portfolio.allocate(data.get('budget',0),data.get('mode',''),data.get('horizon','short'),data.get('stock_budget'),data.get('rotation',0));result['rebalance']=research.rebalance(result)
                for candidate in result.get('alternatives',[])+result.get('singles',[]):candidate['rebalance']=research.rebalance(candidate)
                store.setting('last_recommendation',{'at':stamp(),'result':result})
            elif path=='/api/scan' and mutate:result=alerts.scan()
            elif path=='/api/events/ack' and mutate:store.acknowledge(str(data.get('id','')));result={'ok':True}
            elif path=='/api/events/import' and mutate:result=alerts.import_item(data)
            elif path=='/api/settings' and mutate:
                for k in ['monitor','selflearn','auto_data','auto_promote']:
                    if k in data:
                        if not isinstance(data[k],bool):raise ValueError('设置必须是开关值')
                        store.setting(k,data[k])
                result={'ok':True}
            elif path=='/api/news/check' and not mutate:result=public_news.check()
            elif path=='/api/train' and mutate:
                if models.STATUS['running']:raise ValueError('训练已在进行')
                background(models.train);result={'message':'本地训练已启动；进度见模型实验室'}
            elif path=='/api/update' and mutate:
                if updates.STATUS['running']:raise ValueError('更新已在运行')
                background(lambda:updates.run(train=bool(data.get('train')),refresh_universe=bool(data.get('refresh_universe'))));result={'message':'自动更新流程已启动'}
            elif path=='/api/activate' and mutate:models.activate(str(data.get('version','')));result={'ok':True}
            elif path=='/api/llm/start' and mutate:result=llm.start()
            elif path in ['/','/style.css','/main.js','/enhancements.js','/course.js','/allocation.js','/welcome.js'] and not mutate:
                file=ROOT/'web'/('index.html' if path=='/' else path[1:]);raw=file.read_bytes()
                self.send_response(200);self.send_header('Content-Type',(mimetypes.guess_type(str(file))[0] or 'application/octet-stream')+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(raw);return
            else:return self.reply({'error':'接口不存在'},404)
            self.reply(result)
        except (ValueError,KeyError,market.DataError) as e:self.reply({'error':str(e)},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:
            traceback.print_exc()
            try:self.reply({'error':'处理失败：'+str(e)},500)
            except (BrokenPipeError,ConnectionResetError):pass

def main():
    store.init()
    server=LocalServer(('127.0.0.1',PORT),Handler)
    (ROOT/'logs'/'app.pid').write_text(str(os.getpid()))
    background(alerts.scheduler)
    background(updates.scheduler)
    print(f'InvestLab running at http://127.0.0.1:{PORT}',flush=True)
    if '--open' in sys.argv:webbrowser.open(f'http://127.0.0.1:{PORT}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
