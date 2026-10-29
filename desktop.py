"""Portable desktop launcher. Web UI and all ML libraries are bundled locally."""
import sys,threading,webbrowser,json,traceback,os
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
    import tkinter as tk
    from tkinter import messagebox
    win=tk.Tk();win.title('知衡 InvestLab');win.geometry('450x245');win.configure(bg='#fff7f8')
    tk.Label(win,text='知衡 · 本地投资研究台',font=('Microsoft YaHei',18),bg='#fff7f8',fg='#94505f').pack(pady=(25,10))
    status=tk.StringVar(value='正在启动本地服务…');tk.Label(win,textvariable=status,bg='#fff7f8',wraplength=400).pack(pady=8)
    tk.Label(win,text='界面在本机浏览器打开。保持本窗口运行，\n自动数据更新和新闻巡检才能继续。',bg='#fff7f8').pack(pady=5)
    server=None
    def open_ui():webbrowser.open('http://127.0.0.1:8765/')
    def close():
        if models.STATUS['running'] or updates.STATUS['running']:
            messagebox.showinfo('任务正在运行','请等待当前更新或训练完成后退出。');return
        if server:server.shutdown();server.server_close()
        llm.stop();win.destroy()
    tk.Button(win,text='打开软件界面',command=open_ui,bg='#a65b6a',fg='white',width=20).pack(pady=8)
    win.protocol('WM_DELETE_WINDOW',close)
    try:
        store.init();server=app.LocalServer(('127.0.0.1',app.PORT),app.Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        app.background(alerts.scheduler);app.background(updates.scheduler)
        status.set('已启动 · CPU 本地模型 · 数据留在本机');win.after(500,open_ui)
    except OSError:
        status.set('本机端口已占用。请先关闭其他版本，再重新启动。')
    win.mainloop()

if __name__=='__main__':
    try:main()
    except Exception:
        traceback.print_exc()
        if '--self-test' in sys.argv or '--headless' in sys.argv:sys.exit(1)
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror('启动失败','请查看程序目录 logs/desktop-error.log。')
        except Exception:pass
        sys.exit(1)
