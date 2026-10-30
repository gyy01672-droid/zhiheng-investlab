"""Build a portable Windows program; personal state is never copied into a release."""
from pathlib import Path
import subprocess,sys,shutil,json
ROOT=Path(__file__).resolve().parents[1]
if '--resources-only' not in sys.argv:subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','InvestLab','--distpath',str(ROOT/'output/embedded'),'--workpath',str(ROOT/'tmp/freeze'),'--specpath',str(ROOT/'tmp'),'--collect-all','lightgbm','--collect-submodules','sklearn','--hidden-import','PySide6.QtWebEngineWidgets','--exclude-module','pytest',str(ROOT/'desktop.py')],cwd=ROOT,check=True)
out=ROOT/'output/embedded/InvestLab'
# Qt 6.12 imports the Windows ICU API. PyInstaller can incorrectly collect an
# unrelated ICU 78 from the build host PATH, shadowing that OS API.
for name in ['icuuc.dll','icudt78.dll']:
    wrong=out/'_internal'/name
    if wrong.exists():wrong.unlink()
# Preserve additional certificate policy data used by this Python distribution.
ssl_data=Path(sys.base_prefix)/'Lib/codex-rejected-cas.pem'
if ssl_data.exists():shutil.copy2(ssl_data,out/'_internal/codex-rejected-cas.pem')
for name in ['web','licenses']:shutil.copytree(ROOT/name,out/name,dirs_exist_ok=True)
shutil.copytree(ROOT/'runtime/llama',out/'runtime/llama',dirs_exist_ok=True)
(out/'models').mkdir(exist_ok=True)
for name in ['Qwen3-4B-Instruct-2507-Q4_K_M.gguf','download_manifest.json']:shutil.copy2(ROOT/'models'/name,out/'models'/name)
m=json.loads((ROOT/'data/models/active.json').read_text(encoding='utf-8'))
seed=out/'seed';(seed/'models').mkdir(parents=True,exist_ok=True)
shutil.copytree(ROOT/'data/models'/m['version'],seed/'models'/m['version'],dirs_exist_ok=True)
shutil.copy2(ROOT/'data/models/active.json',seed/'models/active.json');shutil.copy2(ROOT/'data/universe.json',seed/'universe.json')
for name in ['便携版使用说明.md','THIRD_PARTY_NOTICES.md']:shutil.copy2(ROOT/name,out/name)
print(str(out))
