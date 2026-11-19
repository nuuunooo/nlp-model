"""One-time, provenance-checked developer evaluation of a frozen candidate.

The provenance receipt is an offline labeling record, never a runtime user task.
This command does not deploy, publish or alter the production workflow.
"""
import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import catalog, normalize
from scripts.evaluate_description_pipeline import evaluate
from scripts.freeze_candidate import verify


def preflight(dataset, receipt, protocol):
    digest=sha256(dataset.read_bytes()).hexdigest()
    metadata=json.loads(receipt.read_text(encoding='utf-8'))
    if (metadata.get('dataset_sha256')!=digest
            or metadata.get('independently_labeled') is not True
            or metadata.get('proposals_hidden_from_labelers') is not True
            or metadata.get('reserved_before_tuning') is not True
            or not metadata.get('source_provenance') or not metadata.get('labeling_method')):
        raise ValueError('Missing independent-labeling and reserved-test provenance')
    rows=list(csv.DictReader(dataset.open(encoding='utf-8-sig',newline='')))
    required={'record_id','vendor_id','issued_at','description','gold_codes','expected_decision','label_evidence'}
    if not rows or not required.issubset(rows[0]):
        raise ValueError('Test CSV does not satisfy the offline evaluation schema')
    if len({r['record_id'] for r in rows})!=len(rows) or len({normalize(r['description']) for r in rows})!=len(rows):
        raise ValueError('Duplicate test records or descriptions')
    taxonomy,_=catalog()
    support=Counter();decisions=Counter();multi=0
    for row in rows:
        labels=list(filter(None,row['gold_codes'].split('|')))
        if (not row['record_id'].strip() or not row['vendor_id'].strip() or not row['issued_at'].strip()
                or not row['description'].strip() or not row['label_evidence'].strip()
                or len(labels)!=len(set(labels)) or not set(labels).issubset(taxonomy)
                or row['expected_decision'] not in {'accept','clear','abstain'}
                or bool(labels)!=(row['expected_decision']=='accept')):
            raise ValueError('Invalid or incomplete independent gold record')
        support.update(labels);decisions.update([row['expected_decision']]);multi+=len(labels)>1
    if (len(rows)<protocol['minimum_rows'] or multi<protocol['minimum_multi_label_rows']
            or decisions['clear']<protocol['minimum_clear_rows'] or decisions['abstain']<protocol['minimum_abstain_rows']
            or any(support[c]<protocol['minimum_positive_labels_per_category'] for c in taxonomy)):
        raise ValueError('Insufficient category, multi-label, compliant or abstention coverage')
    # Exact overlap with known model/development sources is mechanically rejected.
    used=set()
    archive=Path.home()/'Downloads/marikina_synthetic_dataset_v2.zip'
    if not archive.is_file():
        raise ValueError('Known fit/development source unavailable for overlap audit')
    with ZipFile(archive) as z:
        for name in ('train_fit.jsonl','validation.jsonl','test.jsonl'):
            used.update(normalize(json.loads(line)['description']) for line in z.read(name).splitlines())
    for name in ('market_inspection_eval_multilabel.csv','weightmeasures_eval_120 real records descrpitions.csv','weightmeasures_eval_v2.csv','weightmeasures_eval_v3.csv'):
        source=Path.home()/'Downloads'/name
        if source.is_file():
            used.update(normalize(r['description']) for r in csv.DictReader(source.open(encoding='utf-8-sig',newline='')))
    challenge=ROOT/'evaluation/multi-incident-33/challenge.jsonl'
    if challenge.is_file():
        used.update(normalize(json.loads(line)['description']) for line in challenge.read_text(encoding='utf-8').splitlines())
    if any(normalize(r['description']) in used for r in rows):
        raise ValueError('Test overlaps known fit/development/evaluated descriptions')
    if metadata.get('near_duplicate_and_vendor_group_audit_passed') is not True or not metadata.get('group_audit_method'):
        raise ValueError('Independent near-duplicate and source/vendor grouping audit is required')
    return digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--provenance',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=ROOT/'evaluation/candidate34/frozen_candidate.json')
    args=parser.parse_args()
    candidate=verify(args.manifest)
    if candidate.get('regression_gates_passed') is not True:
        raise ValueError('Candidate failed development regressions; no fresh test will be consumed')
    protocol=json.loads((ROOT/'config/release_protocol.json').read_text(encoding='utf-8'))
    digest=preflight(args.dataset,args.provenance,protocol)
    folder=ROOT/'evaluation/final_tests'/digest
    folder.mkdir(parents=True,exist_ok=True)
    ledger=folder/'attempt.json'
    attempt={'dataset_sha256':digest,'candidate_manifest_sha256':sha256(args.manifest.read_bytes()).hexdigest(),
             'provenance_sha256':sha256(args.provenance.read_bytes()).hexdigest(),'status':'started'}
    with ledger.open('x',encoding='utf-8') as f:
        json.dump(attempt,f,indent=2);f.write('\n')
    try:
        evaluate(args.dataset,'test',ROOT/'models/setfit-e5-synthetic-v2',folder/'evaluation.json',folder/'scores.npz',purpose='untouched_final_test')
        verify(args.manifest)
        report=json.loads((folder/'evaluation.json').read_text(encoding='utf-8'))
        metrics=report['metrics'];targets=protocol['targets']
        checks={'precision':metrics['micro_precision']>=targets['micro_precision'],
                'recall':metrics['micro_recall']>=targets['micro_recall'],
                'multi_label_exact':metrics['pair_rows_both_correct']/metrics['pair_rows']>=targets['multi_label_exact_match_rate'],
                'compliance':metrics['clear_rows_with_actions']<=targets['maximum_clear_rows_with_actions'],
                'abstention':metrics['unclear_rows_with_actions']<=targets['maximum_abstain_rows_with_actions']}
        attempt.update(status='complete',checks=checks,targets_passed=all(checks.values()))
    except Exception as exc:
        attempt.update(status='failed',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        ledger.write_text(json.dumps(attempt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(attempt,indent=2))


if __name__=='__main__':
    main()
