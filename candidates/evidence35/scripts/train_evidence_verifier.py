"""Fit evidence states on fit data; select support cutoff on validation only."""
import argparse
from collections import Counter,defaultdict
import csv
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
        for kind,cap in [('unrelated_target',.5),('hard_negative',1),('unconfirmed_counterfactual',.5),('checked_compliance_counterfactual',.25)]:
            mask=selected & np.array([r['kind']==kind for r in rows])
            if mask.any():raw[mask]*=min(1,raw[natural].sum()*cap/raw[mask].sum())
        raw[selected]*=len(rows)/3/raw[selected].sum()
    return raw


def metrics(rows,probabilities,cutoff):
    import numpy as np
    target=np.array([STATES.index(r['evidence_state']) for r in rows])
    accepted=np.zeros(len(rows),dtype=bool) if cutoff is None else probabilities[:,0]>=cutoff
    truth=target==0;tp=int((accepted&truth).sum());fp=int((accepted&~truth).sum());fn=int((~accepted&truth).sum())
    confusion=np.zeros((3,3),dtype=int)
    for a,b in zip(target,probabilities.argmax(axis=1)):confusion[a,b]+=1
    return {'rows':len(rows),'support_true_positives':tp,'support_false_positives':fp,'support_false_negatives':fn,
            'support_precision':tp/(tp+fp) if tp+fp else 0,'support_recall':tp/(tp+fn) if tp+fn else 0,
            'compliant_rows_accepted':int((accepted&(target==1)).sum()),
            'insufficient_rows_accepted':int((accepted&(target==2)).sum()),
            'argmax_confusion_rows_actual_columns_predicted':confusion.tolist()}


def operational_examples(path, validation_rows, codes):
    audit_path=path.with_name('coverage_and_provenance.json')
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    digest=sha256(path.read_bytes()).hexdigest()
    if digest!=audit['csv_sha256']:
        raise ValueError('Operational CSV does not match its reviewed coverage audit')
    validation_texts={row['description'] for row in validation_rows}
    rows=[]
    records=set()
    keys=set()
    with path.open(encoding='utf-8-sig',newline='') as handle:
        for row in csv.DictReader(handle):
            record,category,state=row['record_id'],row['category'],row['evidence_state']
            quote=normalize(row['evidence_quote'])
            key=(record,row['incident_id'],category)
            if (key in keys or category not in codes or state not in STATES
                    or not quote or row['evidence_quote'] not in row['description']):
                raise ValueError(f'Invalid operational incident {key}')
            if quote in validation_texts or normalize(row['description']) in validation_texts:
                raise ValueError(f'Operational incident overlaps validation text: {key}')
            keys.add(key)
            records.add(record)
            # Repeated incident wording contributes one family within a category/state.
            family='operational:'+category+':'+quote
            rows.append({'description':quote,'target_code':category,'evidence_state':state,
                         'kind':'original','family_ids':[family]})
    if (len(rows),len(records))!=(audit['counts']['incident_rows'],audit['counts']['descriptions']):
        raise ValueError('Operational CSV count does not match its audit')
    provenance={'csv_sha256':digest,'audit_sha256':sha256(audit_path.read_bytes()).hexdigest(),
                'descriptions':len(records),'incident_rows':len(rows),
                'rows_by_state':dict(Counter(row['evidence_state'] for row in rows)),
                'unique_category_state_families':len({(row['family_ids'][0],row['evidence_state']) for row in rows})}
    return rows,provenance


def contrastive_examples(path, codes):
    splits = {"fit": [], "validation": []}
    seen_families = set()
    seen_inputs = set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            split, code = row["split"], row["category"]
            family = (split, code)
            if split not in splits or code not in codes or family in seen_families:
                raise ValueError(f"Invalid contrastive family: {family}")
            seen_families.add(family)
            for state in STATES:
                description = normalize(row[state])
                key = (description, code)
                if not description or key in seen_inputs:
                    raise ValueError(f"Duplicate or empty contrastive input: {family}, {state}")
                seen_inputs.add(key)
                splits[split].append({
                    "description": description, "target_code": code, "evidence_state": state,
                    "kind": "incident_contrast", "family_ids": [f"incident-contrast:{split}:{code}"],
                })
    if seen_families != {(split, code) for split in splits for code in codes}:
        raise ValueError("Each split requires a contrastive family for every category")
    return splits


def hard_negatives(rows, vectors, category_head, codes):
    import numpy as np

    # Only audited single-category source incidents have a complete alternative-category label.
    positives = [row for row in rows if row["kind"] == "original" and row["evidence_state"] == "supported"]
    matrix = np.stack([vectors[row["description"]] for row in positives])
    scores = np.stack(category_head.predict_proba(matrix), axis=1)[:, :, 1]
    negatives = []
    for row, rank in zip(positives, np.argsort(-scores, axis=1, kind="stable"), strict=True):
        for index in rank[:3]:
            code = codes[index]
            if code != row["target_code"]:
                negatives.append({**row, "target_code": code, "evidence_state": "insufficient", "kind": "hard_negative"})
    return negatives


def train(data,encoder_path,output,operational=None,contrastive=None,hard_pairs=False):
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
    if hard_pairs:
        if contrastive is None:
            raise ValueError("Hard nominations require contrastive fit and validation families")
        # Reuse the trusted local SetFit head and its saved category order.
        category_head = joblib.load(encoder_path/'model_head.pkl')
        head_codes = json.loads((encoder_path/'config_setfit.json').read_text(encoding='utf-8'))['labels']
        if head_codes != codes:
            raise ValueError("SetFit category order differs from the policy catalog")
        for rows in (train_rows, val_rows):
            pairs = hard_negatives(rows, vectors, category_head, head_codes)
            by_input = {(row["description"], row["target_code"]): row for row in rows}
            for pair in pairs:
                key = (pair["description"], pair["target_code"])
                if key in by_input and by_input[key]["evidence_state"] != "insufficient":
                    raise ValueError("Hard nomination contradicts an audited incident label")
                by_input[key] = pair
            rows[:] = by_input.values()
    operational_provenance=None
    extra_fit, extra_validation = [], []
    if operational is not None:
        extra,operational_provenance=operational_examples(operational,val_rows,codes)
        extra_fit.extend(extra)
        print(f'Added {len(extra)} operational incident pairs.',flush=True)
    if contrastive is not None:
        contrasts = contrastive_examples(contrastive, codes)
        extra_fit.extend(contrasts["fit"])
        extra_validation.extend(contrasts["validation"])
    if contrastive is not None:
        fit_texts = {row["description"] for row in train_rows + extra_fit}
        validation_texts = {row["description"] for row in val_rows + extra_validation}
        if fit_texts & validation_texts:
            raise ValueError("Fit and validation descriptions overlap")
    missing = list(dict.fromkeys(row["description"] for row in extra_fit + extra_validation
                                 if row["description"] not in vectors))
    if missing:
        body = SetFitClassifier(encoder_path, taxonomy).model.model_body
        queries = ['query: ' + value for value in missing]
        lengths = [len(ids) for ids in body.tokenizer(queries, truncation=False, padding=False)['input_ids']]
        length_lookup.update(zip(missing, lengths))
        valid = [value for value in missing if length_lookup[value] <= body.max_seq_length]
        vectors.update(zip(valid, body.encode(['query: ' + value for value in valid], batch_size=32,
                                              normalize_embeddings=True, show_progress_bar=False,
                                              convert_to_numpy=True)))
        for value in missing:
            if value not in vectors:
                vectors[value] = np.zeros(embeddings.shape[1], dtype=np.float32)
    train_rows.extend(extra_fit)
    val_rows.extend(extra_validation)
    too_long=[r for r in train_rows if length_lookup[r['description']]>512]
    train_rows=[r for r in train_rows if length_lookup[r['description']]<=512]
    category_vectors={c:vectors[t] for c,t in category_text.items()}
    X=features(train_rows,vectors,category_vectors,codes);y=np.array([STATES.index(r['evidence_state']) for r in train_rows])
    weights=weights_for(train_rows)
    print(f'Fitting fixed three-state recipe on {len(train_rows)} audited examples; encoder remains frozen.',flush=True)
    validation_features=features(val_rows,vectors,category_vectors,codes)
    too_long_validation=np.array([length_lookup[r['description']]>512 for r in val_rows])
    targets=np.array([r['evidence_state']=='supported' for r in val_rows])
    compliant=np.array([r['evidence_state']=='compliant' for r in val_rows])
    protected = compliant.copy()
    if contrastive is not None:
        protected |= np.array([r['evidence_state'] == 'insufficient' and r['kind'] not in {'unrelated_target','hard_negative'}
                               for r in val_rows])
    best=None
    for strength in ((0.003, 0.03, 0.3, 4) if contrastive else (4,)):
        candidate=make_pipeline(StandardScaler(),LogisticRegression(C=strength,max_iter=1000,random_state=42))
        candidate.fit(X,y,standardscaler__sample_weight=weights,logisticregression__sample_weight=weights)
        assert list(candidate.classes_)==[0,1,2]
        scores=candidate.predict_proba(validation_features)
        scores[too_long_validation]=[0,0,1]
        cutoff=None
        objective=(0, 0)
        for value in sorted(set(scores[:,0].tolist()),reverse=True):
            accepted=scores[:,0]>=value
            tp=int((accepted&targets).sum());fp=int((accepted&~targets).sum())
            if tp and tp/(tp+fp)>=.98 and not (accepted&protected).any():
                if (tp, -fp) > objective:
                    objective=(tp, -fp)
                    cutoff=value
        print(f'C={strength}: cutoff={cutoff}, validation true supports={objective[0]}',flush=True)
        if best is None or objective > best[0]:
            best=(objective, strength, cutoff, candidate, scores)
    _, strength, cutoff, model, probabilities=best
    compliance_cutoff = None
    if contrastive is not None:
        for value in sorted(set(probabilities[:,1].tolist()), reverse=True):
            accepted = (probabilities.argmax(axis=1) == 1) & (probabilities[:,1] >= value)
            if accepted.any() and not (accepted & ~compliant).any():
                compliance_cutoff = value
    output.mkdir(parents=True)
    joblib.dump(model,output/'head.joblib')
    metadata={'states':STATES,'codes':codes,'feature_version':FEATURE_VERSION,'supported_cutoff':cutoff,
        'compliance_cutoff':compliance_cutoff,
        'policy_sha256':sha256((ROOT/'config/taxonomy.csv').read_bytes()).hexdigest(),
        'hard_nomination_controls':hard_pairs,
        'cutoff_selection':('Validation only. Maximize support recall at >=98% support precision with '
                            'zero compliant acceptances' +
                            (' and zero acceptances on explicit insufficient incidents' if contrastive else '') +
                            '. Prefer the higher cutoff on ties.'),
        'fit_recipe':{'encoder_finetuned':False,'classifier':'StandardScaler + multinomial LogisticRegression','C':strength,'seed':42,'max_iter':1000,
                      'weights':'Equal evidence-state mass; inverse family/kind frequency; counterfactual and unrelated-target mass capped relative to original state examples.'},
        'encoder_path':str(encoder_path),'encoder_identity':identity,
        'data_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (data/'fit.jsonl',data/'validation.jsonl',data/'audit.json')},
        'training_code_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'head_sha256':sha256((output/'head.joblib').read_bytes()).hexdigest(),
        'category_vectors':{c:v.tolist() for c,v in category_vectors.items()},
        'fit_rows':len(train_rows),'fit_too_long_excluded':len(too_long),'max_sequence_length':512,
        'selection_feasible':cutoff is not None,'release_qualified':False,
        'operational_fit_only':operational_provenance,
        'incident_contrasts':({'sha256':sha256(contrastive.read_bytes()).hexdigest(),
                              'fit_rows':len(contrasts['fit']), 'validation_rows':len(contrasts['validation']),
                              'origin':'Authored synthetic development contrasts with disjoint scenario families.'}
                              if contrastive else None),
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
    p.add_argument('--operational',type=Path,help='Add an audited incident CSV to fit only')
    p.add_argument('--contrastive',type=Path,help='Add disjoint, same-category contrast families to fit and validation')
    p.add_argument('--hard-pairs',action='store_true',help='Include plausible wrong-category nominations on audited single incidents')
    a=p.parse_args();train(a.data,a.encoder.resolve(),a.output,a.operational,a.contrastive,a.hard_pairs)
