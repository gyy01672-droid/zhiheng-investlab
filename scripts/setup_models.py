"""Download a pinned CPU runtime and Qwen GGUF, with published hash checks."""
from pathlib import Path
import urllib.request, json, hashlib, zipfile, concurrent.futures, time

ROOT=Path(__file__).resolve().parents[1]
def getjson(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'LocalInvestmentLab/1.0'}),timeout=60))
def download(url,path,sha=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and (not sha or hashlib.sha256(path.read_bytes()).hexdigest()==sha):
        print('Already available:',path.name,flush=True); return
    temp=path.with_suffix(path.suffix+'.part')
    for attempt in range(4):
        try:
            offset=temp.stat().st_size if temp.exists() else 0
            headers={'User-Agent':'LocalInvestmentLab/1.0'}
            if offset: headers['Range']=f'bytes={offset}-'
            with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=90) as r:
                append=offset>0 and r.status==206
                count=offset if append else 0
                mark=count//(128*1024**2)
                with temp.open('ab' if append else 'wb') as f:
                    while True:
                        b=r.read(2*1024**2)
                        if not b: break
                        f.write(b); count+=len(b)
                        if count//(128*1024**2)>mark:
                            mark=count//(128*1024**2); print(path.name,round(count/1024**2),'MiB',flush=True)
            if sha:
                h=hashlib.sha256()
                with temp.open('rb') as f:
                    for b in iter(lambda:f.read(8*1024**2),b''): h.update(b)
                if h.hexdigest()!=sha: raise ValueError('SHA256 mismatch')
            temp.replace(path); print('Verified:',path.name,flush=True); return
        except Exception as e:
            print('Retry',path.name,str(e),flush=True)
            if attempt==3: raise
            time.sleep(3)
def runtime():
    tag='b11951'
    j=getjson('https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/'+tag)
    a=next(x for x in j['assets'] if x['name']==f'llama-{tag}-bin-win-cpu-x64.zip')
    p=ROOT/'runtime'/a['name']
    digest=a.get('digest','') or ''
    download(a['browser_download_url'],p,digest.removeprefix('sha256:') or None)
    target=ROOT/'runtime'/'llama'
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(p) as z:
        for info in z.infolist():
            resolved=(target/info.filename).resolve()
            if not resolved.is_relative_to(target.resolve()): raise ValueError('Unsafe archive path')
        z.extractall(target)
    return {'runtime':tag,'url':a['browser_download_url'],'sha256':digest}
def model():
    repo='unsloth/Qwen3-4B-Instruct-2507-GGUF'
    revision='a06e946bb6b655725eafa393f4a9745d460374c9'
    filename='Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
    j=getjson(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true')
    f=next(x for x in j['siblings'] if x['rfilename']==filename)
    sha=f.get('lfs',{}).get('sha256')
    url=f'https://huggingface.co/{repo}/resolve/{revision}/{filename}?download=true'
    download(url,ROOT/'models'/filename,sha)
    return {'model':repo,'revision':revision,'file':filename,'sha256':sha,'quantization':'Q4_K_M'}
if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        jobs=[ex.submit(runtime),ex.submit(model)]
        results=[j.result() for j in jobs]
    (ROOT/'models'/'download_manifest.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print('All local model assets ready.',flush=True)
