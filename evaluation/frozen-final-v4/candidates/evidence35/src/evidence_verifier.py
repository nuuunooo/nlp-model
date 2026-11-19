"""Three-state category-conditioned evidence classifier on a frozen encoder."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np

STATES=('supported','compliant','insufficient')
FEATURE_VERSION='normalized-e5-text-category-product-distance-onehot-v1'


def features(rows,vectors,category_vectors,codes):
    text=np.array([vectors[row['description']] for row in rows],dtype=np.float32)
    target=np.array([category_vectors[row['target_code']] for row in rows],dtype=np.float32)
    indicator=np.zeros((len(rows),len(codes)),dtype=np.float32)
    indicator[np.arange(len(rows)),[codes.index(row['target_code']) for row in rows]]=1
    return np.hstack((text,text*target,np.abs(text-target),indicator))


class EvidenceVerifier:
    def __init__(self,artifact):
        import joblib
        path=Path(artifact)
        self.metadata=json.loads((path/'metadata.json').read_text(encoding='utf-8'))
        if not self.metadata['selection_feasible'] or self.metadata['supported_cutoff'] is None:
            raise ValueError('Evidence model has no validated support cutoff')
        if self.metadata['feature_version']!=FEATURE_VERSION:raise ValueError('Unsupported evidence feature schema')
        if sha256((path/'head.joblib').read_bytes()).hexdigest()!=self.metadata['head_sha256']:
            raise ValueError('Evidence model checksum mismatch')
        # This is a trusted locally fitted artifact, never an uploaded pickle.
        self.model=joblib.load(path/'head.joblib')
        self.codes=self.metadata['codes']
        self.category_vectors={k:np.array(v,dtype=np.float32) for k,v in self.metadata['category_vectors'].items()}
        self.cutoff=self.metadata['supported_cutoff']

    def probabilities(self,rows,vectors):
        return self.model.predict_proba(features(rows,vectors,self.category_vectors,self.codes))
