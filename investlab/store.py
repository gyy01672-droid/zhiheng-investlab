import sqlite3,json,threading,uuid,math
from decimal import Decimal
from .config import STATE,stamp
from .market import symbol

def db():
    c=sqlite3.connect(STATE/'app.db',timeout=30); c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL'); return c
def init():
    # Snapshot an existing account once per process start, before any schema changes.
    if (STATE/'app.db').exists() and not getattr(init,'backed_up',False):
        from datetime import datetime
        folder=STATE/'backups';folder.mkdir(exist_ok=True)
        dest=sqlite3.connect(folder/('account-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.db'))
        source=sqlite3.connect(STATE/'app.db')
        try:source.backup(dest)
        finally:source.close();dest.close()
        init.backed_up=True
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS lots(id TEXT PRIMARY KEY,code TEXT,name TEXT,price TEXT,quantity INTEGER,fee TEXT,date TEXT);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,code TEXT,title TEXT,published_at TEXT,level TEXT,payload TEXT,created_at TEXT,ack INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY AUTOINCREMENT,started_at TEXT,ended_at TEXT,status TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS trades(id TEXT PRIMARY KEY,code TEXT,name TEXT,side TEXT,price TEXT,quantity INTEGER,fee TEXT,traded_at TEXT,price_source TEXT,confirmed INTEGER,created_at TEXT,voided INTEGER DEFAULT 0);
        ''')
        migrated=c.execute("SELECT value FROM settings WHERE key='ledger_migrated'").fetchone()
        if not migrated:
            for r in c.execute('SELECT * FROM lots').fetchall():
                c.execute('INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,0)',(r['id'],r['code'],r['name'],'BUY',r['price'],r['quantity'],r['fee'],r['date']+'T15:00','旧版手动录入',0,stamp()))
            c.execute("INSERT OR REPLACE INTO settings VALUES ('ledger_migrated','true')")
def get_setting(k,default=None):
    with db() as c: r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone()
    return json.loads(r[0]) if r else default
def setting(k,value):
    with db() as c: c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(k,json.dumps(value,ensure_ascii=False)))
def lots():
    return [dict(r,date=r['traded_at'][:10]) for r in trades() if r['side']=='BUY']
def add_lot(data):
    return add_trade(dict(data,side='BUY',traded_at=data['date']))
def remove_lot(uid):
    return void_trade(uid)

def trades():
    with db() as c:return [dict(r) for r in c.execute('SELECT * FROM trades WHERE voided=0 ORDER BY traded_at,created_at,id')]

def ledger(records):
    """Moving weighted-average cost; FIFO dates are used only for T+1 availability."""
    books={};details=[]
    for r in sorted(records,key=lambda x:(x['traded_at'],x.get('created_at',''),x['id'])):
        code=r['code'];book=books.setdefault(code,{'code':code,'name':r['name'],'quantity':0,'cost':Decimal(0),'realized':Decimal(0),'fees':Decimal(0),'buy_outflow':Decimal(0),'net_sales':Decimal(0),'unconfirmed':0,'inventory':[]})
        p=Decimal(r['price']);fee=Decimal(r['fee']);n=int(r['quantity']);realized=Decimal(0)
        book['fees']+=fee;book['unconfirmed']+=int(not r['confirmed'])
        if r['side']=='BUY':
            book['quantity']+=n;book['cost']+=p*n+fee;book['buy_outflow']+=p*n+fee
            book['inventory'].append({'date':r['traded_at'][:10],'quantity':n})
        else:
            if n>book['quantity']:raise ValueError('卖出数量超过当时持仓，或录入顺序/日期不正确')
            available=sum(x['quantity'] for x in book['inventory'] if x['date']<r['traded_at'][:10])
            if n>available:raise ValueError('卖出数量超过当日可卖股数；A股当天买入不能当天卖出')
            released=book['cost']*n/book['quantity'];net=p*n-fee;realized=net-released
            book['quantity']-=n;book['cost']-=released;book['realized']+=realized;book['net_sales']+=net
            left=n
            for lot in book['inventory']:
                if lot['date']>=r['traded_at'][:10]:continue
                take=min(left,lot['quantity']);lot['quantity']-=take;left-=take
                if left==0:break
            if book['quantity']==0:book['cost']=Decimal(0)
        details.append(dict(r,realized_pnl=float(realized),amount=float(p*n),net_cash=float(-(p*n+fee) if r['side']=='BUY' else p*n-fee)))
    from .config import now
    for b in books.values():
        b['sellable_quantity']=sum(x['quantity'] for x in b.pop('inventory') if x['date']<now().date().isoformat())
        b['average_cost']=float(b['cost']/b['quantity']) if b['quantity'] else 0
        for k in ['cost','realized','fees','buy_outflow','net_sales']:b[k]=float(b[k])
    return {'books':list(books.values()),'trades':details}

def add_trade(data):
    from datetime import datetime
    from .config import now,CN
    code=symbol(data.get('code',''))[2:];side=data.get('side','BUY')
    if side not in ['BUY','SELL']:raise ValueError('请选择买入或卖出记录')
    p=Decimal(str(data['price']));fee=Decimal(str(data.get('fee',0)));n=int(data['quantity'])
    if not p.is_finite() or not fee.is_finite() or p<=0 or fee<0 or fee>p*n or n<=0 or n>100_000_000 or n!=float(data['quantity']):raise ValueError('成交价、数量或费用无效')
    text=str(data.get('traded_at',data.get('date','')))
    if len(text)==10:text+='T15:00'
    dt=datetime.fromisoformat(text)
    if dt.tzinfo is None:dt=dt.replace(tzinfo=CN)
    if dt>now():raise ValueError('成交时间不能晚于当前时间')
    uid=uuid.uuid4().hex
    row={'id':uid,'code':code,'name':str(data.get('name',code))[:80],'side':side,'price':str(p),'quantity':n,'fee':str(fee),
         'traded_at':dt.astimezone(CN).isoformat(timespec='minutes')[:16],'price_source':str(data.get('price_source','手动录入'))[:100],
         'confirmed':int(data.get('confirmed') is True),'created_at':stamp()}
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old=[dict(r) for r in c.execute('SELECT * FROM trades WHERE voided=0')]
        ledger(old+[row])  # Validate the complete historical path before committing a backdated trade.
        c.execute('INSERT INTO trades(id,code,name,side,price,quantity,fee,traded_at,price_source,confirmed,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',tuple(row[k] for k in ['id','code','name','side','price','quantity','fee','traded_at','price_source','confirmed','created_at']))
    return uid

def void_trade(uid):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        remaining=[dict(r) for r in c.execute('SELECT * FROM trades WHERE voided=0 AND id<>?',(uid,))]
        try:ledger(remaining)
        except ValueError as e:raise ValueError('撤销后后续卖出将失去对应持仓，请先撤销相关卖出记录') from e
        c.execute('UPDATE trades SET voided=1 WHERE id=?',(uid,))

def open_codes():return [b['code'] for b in ledger(trades())['books'] if b['quantity']>0]
def mark_pnl(records,price):
    quantity=sum(int(r['quantity']) for r in records)
    cost=sum((Decimal(r['price'])*int(r['quantity'])+Decimal(r['fee']) for r in records),Decimal(0))
    value=Decimal(str(price))*quantity
    return {'quantity':quantity,'cost':float(cost),'market_value':float(value),'pnl':float(value-cost),
            'return_pct':float((value-cost)/cost*100) if cost else None,'average_cost':float(cost/quantity) if quantity else None}
def save_event(code,item,level):
    import hashlib
    # Title fingerprints merge identical reprints; official notice ids remain stable.
    key=hashlib.sha256((code+item['title'].strip()+item.get('published_at','')[:10]).encode()).hexdigest()
    with db() as c:
        r=c.execute('INSERT OR IGNORE INTO events(id,code,title,published_at,level,payload,created_at) VALUES (?,?,?,?,?,?,?)',
                    (key,code,item['title'],item.get('published_at',''),level,json.dumps(item,ensure_ascii=False),stamp()))
        return r.rowcount>0
def events():
    with db() as c:
        out=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY created_at DESC LIMIT 150')]
        scans=[dict(r) for r in c.execute('SELECT * FROM scans ORDER BY id DESC LIMIT 10')]
    for r in out:r['payload']=json.loads(r['payload'])
    return {'events':out,'scans':scans}
def acknowledge(uid):
    with db() as c:c.execute('UPDATE events SET ack=1 WHERE id=?',(uid,))
