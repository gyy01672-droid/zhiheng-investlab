"""Portable desktop launcher. Web UI and all ML libraries are bundled locally."""
import sys,json,traceback,os
from pathlib import Path

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    from investlab.config import ROOT,STATE
    if sys.stdout is None:sys.stdout=(ROOT/'logs'/'desktop-out.log').open('a',encoding='utf-8',buffering=1)
    if sys.stderr is None:sys.stderr=(ROOT/'logs'/'desktop-error.log').open('a',encoding='utf-8',buffering=1)
    if '--self-test' in sys.argv:
        import faulthandler
        faulthandler.dump_traceback_later(20,file=sys.stderr)
    import app
    from investlab import models,llm,store,alerts,updates
    if '--self-test' in sys.argv:
        import urllib.request
        if '--network-check' in sys.argv:
            with urllib.request.urlopen('https://qt.gtimg.cn/q=sh600851',timeout=30) as response:print('HTTPS',response.status,flush=True)
        import numpy as np,lightgbm as lgb
        from scipy.optimize import minimize
        from sklearn.covariance import LedoitWolf
        m=models.info();folder=STATE/'models'/m['version']
        boosters={p.name:lgb.Booster(model_str=p.read_text(encoding='utf-8')).predict(np.zeros((1,14)),num_threads=2).tolist() for p in folder.glob('*.txt')}
        r={'ok':bool(boosters),'models':list(boosters),'version':m['version'],'optimizer':bool(minimize(lambda x:float((x*x).sum()),[1.]).success),'covariance_shape':list(LedoitWolf().fit(np.arange(40).reshape(20,2)).covariance_.shape),'language_model_present':(ROOT/'models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf').exists()}
        (ROOT/'self-test.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');return
    if '--headless' in sys.argv:app.main();return
    from investlab.desktop_window import run
    run(app,models,llm,store,alerts,updates,STATE)

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc()
        if '--self-test' in sys.argv or '--headless' in sys.argv:sys.exit(1)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'启动失败，请查看程序目录 logs/desktop-error.log。','知衡 InvestLab',16)
        except Exception:pass
        sys.exit(1)
