"""Package an explicit resource allowlist; excludes user-data, logs and diagnostics."""
from pathlib import Path
import zipfile,hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
bundle=ROOT/'output/icon-desktop/InvestLab';out=ROOT/'output/release';out.mkdir(exist_ok=True)
allowed=['InvestLab.exe','_internal','licenses','models','runtime','seed','web','便携版使用说明.md','THIRD_PARTY_NOTICES.md']
files=[]
for name in allowed:
    p=bundle/name
    files.extend([p] if p.is_file() else [x for x in p.rglob('*') if x.is_file()])
assert files and any(p.suffix=='.gguf' for p in files)
with zipfile.ZipFile(out/'InvestLab-program.zip','w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
    for p in files:
        if p.suffix!='.gguf':z.write(p,'InvestLab/'+p.relative_to(bundle).as_posix())
with zipfile.ZipFile(ROOT/'output/知衡InvestLab完整便携版.zip','w',zipfile.ZIP_STORED,allowZip64=True) as z:
    for p in files:z.write(p,'InvestLab/'+p.relative_to(bundle).as_posix())
model=bundle/'models/Qwen3-4B-Instruct-2507-Q4_K_M.gguf';parts=[]
with model.open('rb') as src:
    index=1
    while True:
        block=src.read(8*1024*1024)
        if not block:break
        name=f'Qwen-model.part{index}';parts.append(name)
        with (out/name).open('wb') as dest:
            total=0
            while block:
                dest.write(block);total+=len(block)
                if total>=1536*1024*1024:break
                block=src.read(8*1024*1024)
        index+=1
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
manifest={'assets':[{'name':n,'bytes':(out/n).stat().st_size,'sha256':sha(out/n)} for n in ['InvestLab-program.zip']+parts],
          'model':{'name':model.name,'sha256':sha(model),'parts':parts}}
(out/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for name in ['Assemble.ps1','Assemble.cmd']:shutil.copy2(ROOT/'scripts'/name,out/name)
print(json.dumps(manifest,indent=2))
