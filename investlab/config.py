from pathlib import Path
from datetime import datetime, timezone, timedelta
import os,sys,shutil

FROZEN=bool(getattr(sys,'frozen',False))
ROOT=Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parents[1]
STATE=Path(os.getenv('INVESTLAB_STATE',str(ROOT/('user-data' if FROZEN else 'data')))).resolve()
CN=timezone(timedelta(hours=8))
for folder in [STATE,STATE/'cache',STATE/'runs',STATE/'models',ROOT/'logs']:
    folder.mkdir(parents=True,exist_ok=True)
if FROZEN and (ROOT/'seed').exists():
    for source in (ROOT/'seed').rglob('*'):
        target=STATE/source.relative_to(ROOT/'seed')
        if source.is_file() and not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
def now(): return datetime.now(CN)
def stamp(): return now().isoformat(timespec='seconds')
UNIVERSE={
'600519':('贵州茅台','消费'),'000858':('五粮液','消费'),
'600887':('伊利股份','消费'),'000895':('双汇发展','消费'),
'600036':('招商银行','金融'),'601398':('工商银行','金融'),
'601088':('中国神华','能源'),'600900':('长江电力','公用事业'),
'600028':('中国石化','能源'),'600031':('三一重工','工业'),
'600019':('宝钢股份','工业'),'000333':('美的集团','家电'),
'000651':('格力电器','家电'),'600309':('万华化学','材料'),
'002415':('海康威视','科技'),'002371':('北方华创','半导体'),
'002475':('立讯精密','科技'),'000063':('中兴通讯','科技'),
'600050':('中国联通','通信'),'600104':('上汽集团','汽车'),
}
