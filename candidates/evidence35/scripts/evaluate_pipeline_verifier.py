"""Offline regression of strict evidence plus the trained verifier fallback.

Uses original category cutoffs unchanged. It does not deploy or change version
3.3, and these previously inspected cohorts are never called untouched tests.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import re

ROOT=Path(__file__).resolve().parents[1];WORKSPACE=ROOT.parents[1]
sys.path.insert(0,str(ROOT));sys.path.append(str(WORKSPACE))
from src.engine import catalog,normalize
from src.evidence_verifier import EvidenceVerifier
from src.incidents import incident_spans,inference_inputs,UNCERTAIN
from src.neural_verifier import NeuralVerifier
from src.setfit_classifier import SetFitClassifier
from candidates.description34.src.description_evidence import supports_category,COMPLIANT_CATEGORY
from candidates.description34.src.breach_evidence import quantitative_proof,has


COMPLIANCE={
 'Permit & Licensing':r'\bbusiness permit current\b|\bhealth certificate on file\b',
 'Sanitation':r'\b(?:garbage in sealed bags|fish on ice and covered)\b',
 'Stall Occupancy':r'\boccupied by the awardee\b',
 'Stall Rental':r'\brent paid up to date\b',
 'Bladed Instruments':r'\bknives in a locked\b',
 'Market Fees & Surcharges':r'\bdaily fee paid\b',
}


def eligible(code,unit):
    text=unit.text
    if code=='WeightMeasures' or unit.blocked or unit.is_requirement or '?' in unit.context or UNCERTAIN.search(unit.context):return False
    if not supports_category(code,unit.context):return False
    if code in COMPLIANCE and has(COMPLIANCE[code],text):return False
    if code in COMPLIANT_CATEGORY and COMPLIANT_CATEGORY[code].search(text):return False
    if quantitative_proof(code,unit) is False:return False
    if code=='Permit & Licensing' and has(r'construction|counter extension|sidewalk permit|vending permit|scale|event approval|promotion approval',text):return False
    if code=='Permit & Licensing' and has(r'storage room|raised floor|canopy|partition|cabinets?|counter|shelves|pader',text) and has(r'built|building|installed|pinagawa|itinayo|nagkabit|welded|nagdagdag',text) and not has(r'business|meat dealer|lpg retail|sanitary|health|fire safety',text):return False
    if code=='Vendor Identification' and has(r'porter|kargador|mobile vendor id|fake name|hid.{0,20}id|pekeng pangalan',text):return False
    if code=='Stall Occupancy' and has(r'\bdwelling\b',text):return False
    if code=='Illegal Vendor' and not has(r'\b(?:selling|nagtitinda|nagbebenta|hawker|peddler|tinderong)\b',text):return False
    if code=='Stall Management' and has(r'extinguisher',text) and not has(r'duty|contract|requires|must|required',unit.context):return False
    if code=='Lighting Facilities' and not has(r'duty|contract|agreement|kontrata|kasunduan|must|kailangang|dapat|responsib',unit.context):return False
    if code=='Liquor' and has(r'no (?:one|person).{0,30}(?:drinking|selling|serving)|smell of alcohol',text):return False
    if code=='Resisting Authority' and has(r'(?:paid|binayad|binayaran).{0,100}(?:posing|nagpanggap)',text):return False
    if code=='Advertising' and has(r'phone|numbers|numero|receipts|ad texts|ad messages',text) and not has(r'without consent|no consent|walang pahintulot|without permission',text):return False
    if code=='Bladed Instruments' and has(r'utensil|kitchenware',text):return False
    if code=='General Penalties' and has(r'lifted|expired|ended|no longer|not in force',text):return False
    return True


def metrics(decisions):
    known=[r for r in decisions if r['expected_codes'] is not None]
    tp=sum(len(set(r['expected_codes'])&set(r['predicted_codes'])) for r in known)
    fp=sum(len(set(r['predicted_codes'])-set(r['expected_codes'])) for r in known)
    fn=sum(len(set(r['expected_codes'])-set(r['predicted_codes'])) for r in known)
    multi=[r for r in known if len(r['expected_codes'])>1]
    return {'true_positives':tp,'false_positives':fp,'false_negatives':fn,'precision':tp/(tp+fp) if tp+fp else 0,
        'recall':tp/(tp+fn) if tp+fn else 0,'multi_rows':len(multi),
        'multi_exact':sum(set(r['expected_codes'])==set(r['predicted_codes']) for r in multi),
        'clear_false_actions':sum(bool(r['predicted_codes']) for r in decisions if r['expected_decision']=='clear'),
        'unclear_false_actions':sum(bool(r['predicted_codes']) for r in decisions if r['expected_decision']=='abstain')}


class FrozenEncoderScorer:
    def __init__(self,artifact,model_dir):
        self.verifier=EvidenceVerifier(artifact)
        self.cutoff=self.verifier.cutoff
        metadata=self.verifier.metadata
        for name,digest in metadata['encoder_identity'].items():
            if sha256((model_dir/name).read_bytes()).hexdigest()!=digest:
                raise ValueError('Verifier encoder artifact changed: '+name)
        taxonomy,_=catalog()
        if list(taxonomy)!=self.verifier.codes:
            raise ValueError('Verifier categories differ from the frozen catalog')
        self.body=SetFitClassifier(model_dir,taxonomy).model.model_body
        self.max_length=min(self.body.max_seq_length,metadata['max_sequence_length'])

    def score_many(self,rows):
        import numpy as np
        probabilities=np.zeros((len(rows),3))
        probabilities[:,2]=1
        texts=list(dict.fromkeys(row['description'] for row in rows))
        if not texts:
            return probabilities
        queries=['query: '+text for text in texts]
        lengths=self.body.tokenizer(queries,truncation=False,padding=False)['input_ids']
        valid=[text for text,tokens in zip(texts,lengths) if len(tokens)<=self.max_length]
        if valid:
            embeddings=self.body.encode(['query: '+text for text in valid],batch_size=32,
                                         normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True)
            vectors=dict(zip(valid,embeddings))
            indices=[i for i,row in enumerate(rows) if row['description'] in vectors]
            probabilities[indices]=self.verifier.probabilities([rows[i] for i in indices],vectors)
        return probabilities


def main():
    import numpy as np
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',type=Path,default=ROOT/'artifacts/neural-evidence-v2')
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/pipeline-v2')
    args=parser.parse_args()
    artifact=args.artifact
    metadata=json.loads((artifact/'metadata.json').read_text(encoding='utf-8'))
    if not metadata['selection_feasible']:raise ValueError('No feasible validation cutoff; pipeline remains disabled')
    metadata_hash=sha256((artifact/'metadata.json').read_bytes()).hexdigest()
    prior_dir=WORKSPACE/'evaluation/candidate34'
    model_dir=WORKSPACE/'models/setfit-e5-synthetic-v2'
    model=FrozenEncoderScorer(artifact,model_dir) if 'feature_version' in metadata else NeuralVerifier(artifact)
    output=args.output;output.mkdir(exist_ok=False)
    frozen=json.loads((WORKSPACE/'evaluation/frozen-33/manifest.json').read_text(encoding='utf-8'))
    model_identity=frozen['model_provenance']
    thresholds_path=model_dir/'thresholds.json'
    assert sha256(thresholds_path.read_bytes()).hexdigest()==model_identity['thresholds_sha256']
    thresholds=json.loads(thresholds_path.read_text(encoding='utf-8'))['thresholds']
    cohorts=[('validation_verified','validation_final'),('test_regression_verified','test_regression_final'),
             ('market_development_verified','market_development'),('challenge_verified','challenge_regression')]
    for name,cache_name in cohorts:
        if metadata.get('operational_fit_only') and name=='market_development_verified':
            print('Excluded market cohort because its descriptions informed fit.',flush=True)
            continue
        base=json.loads((prior_dir/(name+'.json')).read_text(encoding='utf-8'))
        for p,h in base['source_sha256'].items():
            assert sha256((WORKSPACE/'candidates/description34'/p).read_bytes()).hexdigest()==h,p
        with np.load(prior_dir/(cache_name+'_scores.npz'),allow_pickle=False) as data:
            provenance=json.loads(str(data['provenance']));codes=provenance['codes']
            for key in ('codes','model_sha256','head_sha256','thresholds_sha256'):
                assert provenance[key]==model_identity[key],(cache_name,key)
            for path,digest in provenance['inference_artifacts_sha256'].items():
                assert sha256((model_dir/path).read_bytes()).hexdigest()==digest,(cache_name,path)
            scores={str(t):s for t,s in zip(data['texts'],data['scores'])}
        groups=[inference_inputs(r['description'],normalize) for r in base['decisions']]
        assert sha256(json.dumps(groups,ensure_ascii=False).encode()).hexdigest()==provenance['inference_layout_sha256']
        examples=[];placements=[]
        for i,(row,inputs) in enumerate(zip(base['decisions'],groups)):
            nominations=set()
            for value in inputs:
                nominations.update(c for c,s in zip(codes,scores[value]) if s>=thresholds[c])
            for code in sorted(nominations-set(row['predicted_codes'])):
                for unit in incident_spans(row['description'],normalize):
                    if eligible(code,unit):examples.append({'description':unit.context,'target_code':code});placements.append((i,code))
        unique=list(dict.fromkeys((r['description'],r['target_code']) for r in examples))
        print('Scoring',len(unique),'new evidence candidates for',name,flush=True)
        probabilities=model.score_many([{'description':t,'target_code':c} for t,c in unique])
        lookup=dict(zip(unique,probabilities))
        decisions=[{k:r[k] for k in ('scenario_id','expected_codes','expected_decision','predicted_codes')} for r in base['decisions']]
        predictions=[set(r['predicted_codes']) for r in decisions]
        for row,(i,code) in zip(examples,placements):
            if lookup[(row['description'],code)][0]>=model.cutoff:predictions[i].add(code)
        for r,pred in zip(decisions,predictions):r['predicted_codes']=sorted(pred)
        report={'purpose':'previously_inspected_development_regression_not_fresh_test',
                'method':'Frozen strict-34 findings plus original thresholded category nominations accepted by a trained three-state verifier. Scope/uncertainty/numeric vetoes remain mandatory. No gold enters inference.',
                'verifier_metadata_sha256':metadata_hash,'supported_cutoff':model.cutoff,
                'score_cache_sha256':sha256((prior_dir/(cache_name+'_scores.npz')).read_bytes()).hexdigest(),
                'base_report_sha256':sha256((prior_dir/(name+'.json')).read_bytes()).hexdigest(),
                'scoring_code_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
                'unique_incident_category_pairs_scored':len(unique),
                'metrics':metrics(decisions),'strict_base_metrics':metrics(base['decisions']),'decisions':decisions}
        (output/(name+'.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        print(name,json.dumps(report['metrics']),flush=True)
    assert sha256((artifact/'metadata.json').read_bytes()).hexdigest()==metadata_hash


if __name__=='__main__':main()
