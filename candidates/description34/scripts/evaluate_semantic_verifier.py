"""Validation-only comparison of a semantic fallback; never deploys it."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.engine import normalize
from src.incidents import incident_spans, inference_inputs
from src.semantic_evidence import SemanticEvidence,eligible,HYPOTHESES


def main():
    import numpy as np
    root=Path('evaluation/candidate34')
    report=json.loads((root/'validation_final.json').read_text(encoding='utf-8'))
    rows=report['decisions']
    with np.load(root/'validation_final_scores.npz',allow_pickle=False) as data:
        scores={str(t):s for t,s in zip(data['texts'],data['scores'])}
        codes=json.loads(str(data['provenance']))['codes']
    cutoffs=json.loads(Path('models/setfit-e5-synthetic-v2/thresholds.json').read_text())['thresholds']
    pairs=[];indices=[]
    for index,row in enumerate(rows):
        nominations=set()
        for text in inference_inputs(row['description'],normalize):
            nominations.update(code for code,score in zip(codes,scores.get(text,np.zeros(len(codes)))) if score>=cutoffs[code])
        for code in nominations-set(row['predicted_codes']):
            for unit in incident_spans(row['description'],normalize):
                if eligible(code,unit):
                    pairs.append((code,unit.context));indices.append((index,code))
    unique=list(dict.fromkeys(pairs))
    model=SemanticEvidence('models/semantic-evidence')
    provenance={'model':model.provenance,'hypotheses':HYPOTHESES,
                'pairs_sha256':sha256(json.dumps(unique,ensure_ascii=False).encode()).hexdigest(),
                'eligibility_sha256':sha256(Path('src/semantic_evidence.py').read_bytes()).hexdigest()}
    cache=root/'semantic_validation_facts_scores.npz'
    if cache.exists():
        with np.load(cache,allow_pickle=False) as data:
            if json.loads(str(data['provenance']))!=provenance:raise ValueError('Semantic cache changed')
            raw=data['scores']
    else:
        print('Scoring',len(unique),'validation-only semantic pairs',flush=True)
        raw=model.score_many(unique)
        np.savez_compressed(cache,scores=raw,provenance=json.dumps(provenance))
    lookup=dict(zip(unique,raw));outcomes=[]
    for threshold in [.05,.1,.15,.2,.25,.3,.4,.5,.6,.7,.8,.9,.95]:
        predicted=[set(r['predicted_codes']) for r in rows]
        for pair,(index,code) in zip(pairs,indices):
            if lookup[pair]>=threshold:predicted[index].add(code)
        tp=fp=fn=clear=unclear=exact=0
        for row,pred in zip(rows,predicted):
            gold=row['expected_codes']
            if gold is not None:
                tp+=len(set(gold)&pred);fp+=len(pred-set(gold));fn+=len(set(gold)-pred)
                exact+=set(gold)==pred
            if row['expected_decision']=='clear':clear+=bool(pred)
            if row['expected_decision']=='abstain':unclear+=bool(pred)
        outcomes.append({'threshold':threshold,'true_positives':tp,'false_positives':fp,'false_negatives':fn,'precision':tp/(tp+fp),'recall':tp/(tp+fn),'clear_false_actions':clear,'unclear_false_actions':unclear,'exact':exact})
    result={'purpose':'validation_only_architecture_experiment_not_deployed','provenance':provenance,'pairs':len(unique),'threshold_comparison':outcomes,
            'adoption_target':{'precision':.98318,'recall':.78799,'clear_false_actions':0,'unclear_false_actions':0}}
    (root/'semantic_validation_facts_experiment.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(outcomes,indent=2),flush=True)


if __name__=='__main__':main()
