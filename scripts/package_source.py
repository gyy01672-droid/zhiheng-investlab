from pathlib import Path
import zipfile,hashlib,json
root=Path(__file__).resolve().parents[1]
files=[]
for folder in ['investlab','web','tests','scripts','licenses']:
    files += [p for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
files += [root/n for n in ['desktop.py','便携版使用说明.md','参考项目对比与优化建议.md','THIRD_PARTY_NOTICES.md','app.py','课程要求实现对照.md','README.md','requirements.txt','requirements.lock.txt','启动软件.cmd','启动软件.ps1','停止软件.cmd','停止软件.ps1','更新数据并训练.cmd','pytest.ini']]
files += list((root/'data'/'models').glob('*/manifest.json'))+list((root/'data'/'models').glob('*/*.txt'))+list((root/'data'/'models').glob('*/long.json'))+[root/'data/models/active.json']
files += [root/'data/universe.json']
files = [p for p in files if p.name not in ['upgrade_ui.py','verify_v2.py','weibo.py']]
out=root/'output'/'知衡投资研究软件源码.zip'
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(root).as_posix())
print(out)
print('files',len(files),'bytes',out.stat().st_size)
