"""Local trained evidence probabilities; absent calibration fails closed."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from .engine import normalize


class NeuralVerifier:
    def __init__(self,path):
        from setfit import SetFitModel
        self.path=Path(path)
        self.metadata=json.loads((self.path/'metadata.json').read_text(encoding='utf-8'))
        if not self.metadata['selection_feasible'] or self.metadata['supported_cutoff'] is None:
            raise ValueError('Neural verifier has no validated support cutoff')
        identity=json.loads((self.path/'artifact_identity.json').read_text(encoding='utf-8'))
        for name,h in identity.items():
            if sha256((self.path/name).read_bytes()).hexdigest()!=h:raise ValueError('Verifier artifact changed: '+name)
        self.model=SetFitModel.from_pretrained(str(self.path/'model'),device='cpu',local_files_only=True)
        if self.model.labels!=['supported','compliant','insufficient']:raise ValueError('Wrong evidence state order')
        self.cutoff=self.metadata['supported_cutoff']

    def score_many(self,rows):
        inputs=['query: Category: '+r['target_code']+'. Incident: '+normalize(r['description']) for r in rows]
        lengths=[len(v) for v in self.model.model_body.tokenizer(inputs,truncation=False,padding=False)['input_ids']]
        result=np.zeros((len(rows),3));result[:,2]=1
        valid=[i for i,n in enumerate(lengths) if n<=512]
        for start in range(0,len(valid),256):
            ids=valid[start:start+256]
            result[ids]=self.model.predict_proba([inputs[i] for i in ids],as_numpy=True,show_progress_bar=False)
        return result
