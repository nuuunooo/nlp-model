"""Freeze a reviewable runtime and model identity before a one-time fresh test."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.engine import RULE_PIPELINE_VERSION


def hashes(root=ROOT):
    files = [p for folder in ('src','config','sql') for p in (root/folder).rglob('*')
             if p.is_file() and '__pycache__' not in p.parts]
    files += list((root/'scripts').glob('*.py'))
    model = root/'models/setfit-e5-synthetic-v2'
    files += [p for p in model.rglob('*') if p.is_file()]
    return {str(p.relative_to(root)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def verify(manifest, root=ROOT):
    saved = json.loads(Path(manifest).read_text(encoding='utf-8'))
    current = hashes(root)
    if current != saved['files_sha256'] or saved['version'] != RULE_PIPELINE_VERSION:
        changed = sorted(set(current)^set(saved['files_sha256']) | {p for p in current if p in saved['files_sha256'] and current[p]!=saved['files_sha256'][p]})
        raise ValueError('Frozen candidate changed: '+', '.join(changed))
    return saved


def regression_gates(root=ROOT):
    checks={}
    for candidate,baseline,label in (
        ('validation_verified.json','validation_regression.json','validation'),
        ('test_regression_verified.json','test_regression.json','historical_regression'),
    ):
        current=json.loads((root/'evaluation/candidate34'/candidate).read_text(encoding='utf-8'))
        prior=json.loads((root/'evaluation/multi-incident-33'/baseline).read_text(encoding='utf-8'))
        for name,expected in current['source_sha256'].items():
            if sha256((root/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('Candidate report does not match frozen source: '+name)
        new,old=current['metrics'],prior['metrics']
        checks[label]={
            'precision_preserved':new['micro_precision']>=old['micro_precision'],
            'recall_preserved':new['micro_recall']>=old['micro_recall'],
            'compliance_preserved':new['clear_rows_with_actions']<=old['clear_rows_with_actions'],
            'abstention_preserved':new['unclear_rows_with_actions']<=old['unclear_rows_with_actions'],
            'multi_label_exact_preserved':new['pair_rows_both_correct']>=old['pair_rows_both_correct'],
        }
    return checks


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'evaluation/candidate34/frozen_candidate.json')
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.verify:
        result=verify(args.output)
        print('Frozen candidate identity verified for',result['version'])
    else:
        gates=regression_gates()
        passed=all(value for group in gates.values() for value in group.values())
        result={'version':RULE_PIPELINE_VERSION,
                'status':'eligible_for_final_test' if passed else 'rejected_by_development_regressions',
                'regression_gates':gates,'regression_gates_passed':passed,
                'files_sha256':hashes(), 'test_status':'not_run_no_eligible_untouched_set_found'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as f:
            json.dump(result,f,indent=2);f.write('\n')
        print('Saved',args.output)
