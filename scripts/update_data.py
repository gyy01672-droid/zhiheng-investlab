"""User-callable network acquisition and local learning, without any cloud model."""
import sys,argparse,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from investlab import store,updates
parser=argparse.ArgumentParser(description='Refresh public evidence and optionally train a local candidate')
parser.add_argument('--train',action='store_true');parser.add_argument('--refresh-universe',action='store_true')
args=parser.parse_args();store.init()
print(json.dumps(updates.run(train=args.train,refresh_universe=args.refresh_universe),ensure_ascii=False,indent=2))
