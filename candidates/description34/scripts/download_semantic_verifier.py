"""Download only pinned, public model data; never upload inspection records."""
from hashlib import sha256
import json
from pathlib import Path
import requests

REPO='MoritzLaurer/mDeBERTa-v3-base-mnli-xnli'
REVISION='8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c'
ROOT=Path(__file__).resolve().parents[1]/'models/semantic-evidence'
FILES=('config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json',
       'added_tokens.json','spm.model','README.md','onnx/model_quantized.onnx')


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    result={'repository':REPO,'revision':REVISION,'files':{}}
    tree=requests.get(f'https://huggingface.co/api/models/{REPO}/tree/{REVISION}/onnx',timeout=30)
    tree.raise_for_status()
    weight=next(row for row in tree.json() if row['path']=='onnx/model_quantized.onnx')
    expected=weight.get('lfs',{}).get('oid')
    if not expected:
        raise ValueError('Missing authoritative LFS checksum')
    for name in FILES:
        target=ROOT/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            response=requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}',stream=True,timeout=(30,60))
            response.raise_for_status()
            temporary=target.with_suffix(target.suffix+'.part')
            total=0;next_notice=64*1024*1024
            with temporary.open('wb') as out:
                for block in response.iter_content(1024*1024):
                    out.write(block);total+=len(block)
                    if total>=next_notice:
                        print(f'{name}: {total//(1024*1024)} MiB',flush=True);next_notice+=64*1024*1024
            if name.startswith('onnx/') and sha256(temporary.read_bytes()).hexdigest()!=expected:
                raise ValueError('Downloaded model failed authoritative LFS checksum')
            temporary.replace(target)
        actual=sha256(target.read_bytes()).hexdigest()
        if name.startswith('onnx/') and actual!=expected:
            raise ValueError('Existing model failed authoritative LFS checksum')
        result['files'][name]={'sha256':actual,'bytes':target.stat().st_size}
        print('Verified',name,flush=True)
    (ROOT/'provenance.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
