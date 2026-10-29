"""Epsilon-greedy candidate discovery, never random capital allocation."""
import random,math,json,secrets
from . import universe
from .config import STATE,stamp

def select(base,meta,epsilon,rng=None):
    epsilon=float(epsilon)
    if not math.isfinite(epsilon) or not 0<=epsilon<=.5:raise ValueError('探索概率应在0至50%之间')
    rng=rng or random.Random(secrets.randbits(64))
    blocked=set(meta.get('training_symbols',[]))|set(meta.get('heldout_symbols',[]))|set(base)
    directory=universe.current() or {'stocks':{}}
    unseen=[code for code,r in directory['stocks'].items() if code not in blocked and not code.startswith(('688','300','301')) and not any(w in r.get('name','').upper() for w in ['ST','退'])]
    rng.shuffle(unseen);result=[];explored=[]
    for code in base:
        if unseen and rng.random()<epsilon:code=unseen.pop();explored.append(code)
        result.append(code)
    return result,{'epsilon':epsilon,'selected_codes':result,'explored_codes':explored,'exploration_count':len(explored),'candidate_count':len(result),'directory_updated_at':directory.get('updated_at'),'scope':'仅在当前联网行业目录内探索训练池外股票；保留独立留出组，不是全A股实时搜索。'}

def record(info,approved,failed,version):
    # Separate observations never become model-training labels automatically.
    folder=STATE/'exploration';folder.mkdir(exist_ok=True)
    payload=dict(info,at=stamp(),model_version=version,approved=[{'code':c['code'],'prediction':c['prediction']} for c in approved],excluded=failed,note='待5/60交易日结果成熟后独立评估；本记录不证明收益改善。')
    (folder/(secrets.token_hex(8)+'.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
