"""Fit evidence states on fit data; select support cutoff on validation only."""
import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import catalog,normalize
from src.evidence_verifier import STATES,FEATURE_VERSION,features
from src.setfit_classifier import SetFitClassifier


def weights_for(rows):
    import numpy as np
    groups=Counter((r['evidence_state'],r['kind'],tuple(r['family_ids'])) for r in rows)
    raw=np.array([1/groups[(r['evidence_state'],r['kind'],tuple(r['family_ids']))] for r in rows])
    for state in STATES:
        selected=np.array([r['evidence_state']==state for r in rows])
        natural=selected & np.array([r['kind']=='original' for r in rows])
        if not natural.any():raise ValueError('Every evidence state needs genuine source examples')
        for kind,cap in [('unrelated_target',.5),('unconfirmed_counterfactual',.5),('checked_compliance_counterfactual',.25)]:
            mask=selected & np.array([r['kind']==kind for r in rows])
            if mask.any():raw[mask]*=min(1,raw[natural].sum()*cap/raw[mask].sum())
        raw[selected]*=len(rows)/3/raw[selected].sum()
    return raw


def metrics(rows,probabilities,cutoff):
    import numpy as np
    target=np.array([STATES.index(r['evidence_state']) for r in rows])
    accepted=probabilities[:,0]>=cutoff
    truth=target==0;tp=int((accepted&truth).sum());fp=int((accepted&~truth).sum());fn=int((~accepted&truth).sum())
    confusion=np.zeros((3,3),dtype=int)
    for a,b in zip(target,probabilities.argmax(axis=1)):confusion[a,b]+=1
    return {'rows':len(rows),'support_true_positives':tp,'support_false_positives':fp,'support_false_negatives':fn,
            'support_precision':tp/(tp+fp) if tp+fp else 0,'support_recall':tp/(tp+fn) if tp+fn else 0,
            'compliant_rows_accepted':int((accepted&(target==1)).sum()),
            'insufficient_rows_accepted':int((accepted&(target==2)).sum()),
            'argmax_confusion_rows_actual_columns_predicted':confusion.tolist()}


def train(data,encoder_path,output):
    import joblib
    import numpy as np
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    if output.exists():raise FileExistsError('Use a new evidence model output')
    train_rows=[json.loads(x) for x in (data/'fit.jsonl').read_text(encoding='utf-8').splitlines()]
    val_rows=[json.loads(x) for x in (data/'validation.jsonl').read_text(encoding='utf-8').splitlines()]
    taxonomy,_=catalog();codes=list(taxonomy)
    for rows in (train_rows,val_rows):
        for r in rows:r['description']=normalize(r['description'])
    category_text={c:normalize(c+'. '+taxonomy[c]['evidence_requirement_en']) for c in codes}
    texts=list(dict.fromkeys([r['description'] for r in train_rows+val_rows]+list(category_text.values())))
    identity={p.name:sha256(p.read_bytes()).hexdigest() for p in encoder_path.iterdir()
              if p.is_file() and p.name not in {'README.md','evaluation.json','model_head.pkl','thresholds.json'}}
    provenance={'encoder_sha256':identity,'input_sha256':sha256(json.dumps(texts,ensure_ascii=False).encode()).hexdigest(),
                'normalizer_sha256':sha256((ROOT/'src/engine.py').read_bytes()).hexdigest()}
    cache=ROOT/'evaluation/evidence_embeddings_v1.npz'
    if cache.exists():
        with np.load(cache,allow_pickle=False) as saved:
            if json.loads(str(saved['provenance']))!=provenance:raise ValueError('Embedding provenance mismatch')
            embeddings=saved['embeddings'];lengths=saved['lengths']
    else:
        classifier=SetFitClassifier(encoder_path,taxonomy)
        body=classifier.model.model_body
        queries=['query: '+t for t in texts]
        tokenized=body.tokenizer(queries,truncation=False,padding=False)
        lengths=np.array([len(v) for v in tokenized['input_ids']])
        embeddings=np.zeros((len(texts),body.get_sentence_embedding_dimension()),dtype=np.float32)
        valid=np.flatnonzero(lengths<=body.max_seq_length)
        for start in range(0,len(valid),512):
            positions=valid[start:start+512]
            embeddings[positions]=body.encode([queries[i] for i in positions],batch_size=32,
                                               normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True)
            print(f'Embedded {min(start+512,len(valid))}/{len(valid)} complete contexts',flush=True)
        np.savez_compressed(cache,embeddings=embeddings,lengths=lengths,provenance=json.dumps(provenance))
    vectors=dict(zip(texts,embeddings));length_lookup=dict(zip(texts,lengths))
    too_long=[r for r in train_rows if length_lookup[r['description']]>512]
    train_rows=[r for r in train_rows if length_lookup[r['description']]<=512]
    category_vectors={c:vectors[t] for c,t in category_text.items()}
    X=features(train_rows,vectors,category_vectors,codes);y=np.array([STATES.index(r['evidence_state']) for r in train_rows])
    weights=weights_for(train_rows)
    model=make_pipeline(StandardScaler(),LogisticRegression(C=4,max_iter=1000,random_state=42))
    print(f'Fitting fixed three-state recipe on {len(train_rows)} audited examples; encoder remains frozen.',flush=True)
    model.fit(X,y,standardscaler__sample_weight=weights,logisticregression__sample_weight=weights)
    assert list(model.classes_)==[0,1,2]
    probabilities=model.predict_proba(features(val_rows,vectors,category_vectors,codes))
    for i,r in enumerate(val_rows):
        if length_lookup[r['description']]>512:probabilities[i]=[0,0,1]
    # Exactly one cutoff selection procedure, using validation only. Wrong-target
    # evidence counts as false support, not a compliant or supported incident.
    targets=np.array([r['evidence_state']=='supported' for r in val_rows])
    compliant=np.array([r['evidence_state']=='compliant' for r in val_rows])
    best=None
    for value in sorted(set(probabilities[:,0].tolist()),reverse=True):
        accepted=probabilities[:,0]>=value
        tp=int((accepted&targets).sum());fp=int((accepted&~targets).sum())
        precision=tp/(tp+fp) if tp+fp else 0
        if tp and precision>=.98 and not (accepted&compliant).any():
            objective=(tp/(targets.sum()),value)
            if best is None or objective>best[0]:best=(objective,value)
    cutoff=best[1] if best else 1.0
    output.mkdir(parents=True)
    joblib.dump(model,output/'head.joblib')
    metadata={'states':STATES,'codes':codes,'feature_version':FEATURE_VERSION,'supported_cutoff':cutoff,
        'cutoff_selection':'Validation only; maximize support recall subject to >=98% support precision and zero compliant validations accepted; prefer higher cutoff on ties.',
        'fit_recipe':{'encoder_finetuned':False,'classifier':'StandardScaler + multinomial LogisticRegression','C':4,'seed':42,'max_iter':1000,
                      'weights':'Equal evidence-state mass; inverse family/kind frequency; counterfactual and unrelated-target mass capped relative to original state examples.'},
        'encoder_path':str(encoder_path),'encoder_identity':identity,
        'data_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (data/'fit.jsonl',data/'validation.jsonl',data/'audit.json')},
        'training_code_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'head_sha256':sha256((output/'head.joblib').read_bytes()).hexdigest(),
        'category_vectors':{c:v.tolist() for c,v in category_vectors.items()},
        'fit_rows':len(train_rows),'fit_too_long_excluded':len(too_long),'max_sequence_length':512,
        'selection_feasible':best is not None,'release_qualified':False,
        'validation':metrics(val_rows,probabilities,cutoff),
        'validation_by_kind':{kind:metrics([r for r in val_rows if r['kind']==kind],probabilities[[r['kind']==kind for r in val_rows]],cutoff)
                              for kind in sorted({r['kind'] for r in val_rows})}}
    (output/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    np.savez_compressed(output/'validation_probabilities.npz',probabilities=probabilities)
    print(json.dumps({k:metadata[k] for k in ('fit_rows','fit_too_long_excluded','supported_cutoff','selection_feasible','validation','validation_by_kind')},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,default=ROOT/'data/evidence-v2')
    p.add_argument('--encoder',type=Path,default=ROOT.parents[1]/'models/setfit-e5-synthetic-v2')
    p.add_argument('--output',type=Path,default=ROOT/'artifacts/evidence-verifier-v1')
    a=p.parse_args();train(a.data,a.encoder.resolve(),a.output)
