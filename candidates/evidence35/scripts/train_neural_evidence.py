"""Train a separate three-state encoder with a fixed, fit-only recipe."""
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import normalize
from scripts.train_evidence_verifier import metrics,STATES


def text_input(row):
    return 'query: Category: '+row['target_code']+'. Incident: '+normalize(row['description'])


def select_fit(rows):
    selected=[r for r in rows if r['kind']=='original']
    # Preserve original examples and bound generated language/category contrasts.
    # No validation labels or descriptions affect this deterministic selection.
    for kind,n in [('unrelated_target',2),('unconfirmed_counterfactual',2)]:
        buckets=defaultdict(list)
        for row in rows:
            if row['kind']==kind:buckets[(row['target_code'],row['language'])].append(row)
        selected.extend(r for key in sorted(buckets) for r in buckets[key][:n])
    codes=sorted({r['target_code'] for r in rows})
    for i,code in enumerate(codes):
        lang=('en','fil','taglish')[i%3]
        selected.append(next(r for r in rows if r['kind']=='checked_compliance_counterfactual' and r['target_code']==code and r['language']==lang))
    return selected


def main():
    import numpy as np
    from datasets import Dataset
    from sentence_transformers import SentenceTransformer
    from setfit import SetFitModel,Trainer,TrainingArguments
    from sklearn.linear_model import LogisticRegression
    from transformers import set_seed
    set_seed(42)
    source=ROOT.parents[1]/'models/setfit-e5-synthetic-v2'
    data=ROOT/'data/evidence-v2';output=ROOT/'artifacts/neural-evidence-v2'
    if output.exists():raise FileExistsError('Use a new model directory')
    source_identity={str(p.relative_to(source)):sha256(p.read_bytes()).hexdigest() for p in source.rglob('*')
                     if p.is_file() and p.name not in {'README.md','evaluation.json'}}
    code_identity={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in
                   (Path(__file__),ROOT/'scripts/train_evidence_verifier.py',ROOT/'src/engine.py')}
    all_rows=[json.loads(x) for x in (data/'fit.jsonl').read_text(encoding='utf-8').splitlines()]
    fit=select_fit(all_rows)
    validation=[json.loads(x) for x in (data/'validation.jsonl').read_text(encoding='utf-8').splitlines()]
    body=SentenceTransformer(str(source),device='cpu',local_files_only=True,trust_remote_code=False,
                             model_kwargs={'use_safetensors':True})
    inputs=[text_input(r) for r in fit]
    lengths=[len(x) for x in body.tokenizer(inputs,truncation=False,padding=False)['input_ids']]
    excluded=sum(v>512 for v in lengths)
    fit=[r for r,n in zip(fit,lengths) if n<=512]
    inputs=[text_input(r) for r in fit]
    dataset=Dataset.from_dict({'text':inputs,'label':[STATES.index(r['evidence_state']) for r in fit]})
    model=SetFitModel(model_body=body,model_head=LogisticRegression(C=1,class_weight='balanced',max_iter=1000),
                      normalize_embeddings=True,labels=list(STATES))
    output.parent.mkdir(parents=True,exist_ok=True)
    args=TrainingArguments(output_dir=str(ROOT/'evaluation/neural-evidence-training'),batch_size=8,num_epochs=1,
                           max_steps=100,num_iterations=10,save_strategy='no',report_to=[],seed=42,logging_steps=10)
    print(json.dumps({'fit_rows':len(fit),'states':dict(Counter(r['evidence_state'] for r in fit)),
                      'kinds':dict(Counter(r['kind'] for r in fit)),'fixed_steps':100,'validation_used_for_fitting':False}),flush=True)
    Trainer(model=model,args=args,train_dataset=dataset).train()
    val_inputs=[text_input(r) for r in validation]
    val_lengths=[len(x) for x in body.tokenizer(val_inputs,truncation=False,padding=False)['input_ids']]
    probabilities=np.zeros((len(validation),3));probabilities[:,2]=1
    valid=[i for i,n in enumerate(val_lengths) if n<=512]
    for start in range(0,len(valid),256):
        ids=valid[start:start+256]
        probabilities[ids]=model.predict_proba([val_inputs[i] for i in ids],as_numpy=True,show_progress_bar=False)
    targets=np.array([r['evidence_state']=='supported' for r in validation])
    compliant=np.array([r['evidence_state']=='compliant' for r in validation])
    best=None
    for cutoff in sorted(set(probabilities[:,0].tolist()),reverse=True):
        accepted=probabilities[:,0]>=cutoff;tp=int((accepted&targets).sum());fp=int((accepted&~targets).sum())
        if tp and tp/(tp+fp)>=.98 and not (accepted&compliant).any():
            rank=(tp/targets.sum(),cutoff)
            if best is None or rank>best[0]:best=(rank,cutoff)
    cutoff=best[1] if best else None
    for p,h in code_identity.items():
        if sha256((ROOT/p).read_bytes()).hexdigest()!=h:raise ValueError('Training code changed during fit')
    for p,h in source_identity.items():
        if sha256((source/p).read_bytes()).hexdigest()!=h:raise ValueError('Original classifier artifact changed')
    output.mkdir()
    model.save_pretrained(str(output/'model'))
    (output/'model/README.md').write_text('# Local three-state evidence verifier\n',encoding='utf-8')
    result={'states':STATES,'supported_cutoff':cutoff,'selection_feasible':best is not None,'release_qualified':False,
            'recipe':{'encoder':'separate copy of original multilingual E5; original classifier unchanged','steps':100,'batch_size':8,'seed':42,
                      'contrastive_iterations':10,'head_C':1,'head_class_weight':'balanced'},
            'fit_rows':len(fit),'fit_states':dict(Counter(r['evidence_state'] for r in fit)),
            'fit_kinds':dict(Counter(r['kind'] for r in fit)),'oversized_fit_rows_excluded':excluded,
            'source_classifier_identity':source_identity,'training_code_sha256':code_identity,
            'data_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (data/'fit.jsonl',data/'validation.jsonl',data/'audit.json')},
            'input_format':'query: Category: <predicted category>. Incident: <normalized description context>',
            'selection':'Validation only: maximize support recall with >=98% support precision and zero compliant validation cases accepted; higher cutoff on ties.',
            'validation':metrics(validation,probabilities,cutoff),
            'validation_by_language':{language:metrics([r for r in validation if r['language']==language],
                probabilities[[r['language']==language for r in validation]],cutoff) for language in ('fil','en','taglish')}}
    (output/'metadata.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    np.savez_compressed(output/'validation_probabilities.npz',probabilities=probabilities)
    print(json.dumps({k:result[k] for k in ('fit_rows','supported_cutoff','selection_feasible','validation','validation_by_language')},indent=2),flush=True)


if __name__=='__main__':main()
