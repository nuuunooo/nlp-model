"""Build auditable, category-conditioned evidence examples from supplied scenarios.

No code from the supplied archive is executed. Multi-violation record labels are
never inherited by their sentences. Original files and gold labels are unchanged.
"""
import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import catalog,normalize

STATES=('supported','compliant','insufficient')


def audit_positive(row,scenario):
    if len(row['expected_codes'])!=1 or len(scenario['findings'])!=1:
        return 'multi_incident_requires_span_labels'
    finding=scenario['findings'][0]
    if finding['category']!=row['expected_codes'][0]:
        return 'category_metadata_mismatch'
    if finding['responsible_party'] not in {'seller','stallholder','vendor','helper','porter','operator','awardee','occupant'}:
        return 'responsible_party_not_supported'
    facts=row['observed_facts']
    observation=' '.join(f[13:] for f in facts if f.startswith('Observation: '))
    requirement=' '.join(f[13:] for f in facts if f.startswith('Requirement: '))
    if not observation:
        return 'no_structured_observation'
    if finding['responsibility_basis']=='duty' and not requirement:
        return 'duty_missing'
    if 'without consent' in requirement.lower() and not re.search(r'without consent|no consent|never agreed|did not consent',observation,re.I):
        return 'consent_absence_only_in_requirement'
    if finding['observation_id']=='used_as_residence':
        return 'dwelling_category_boundary_unresolved'
    if row['language']=='en':
        if normalize(observation) not in normalize(row['description']):
            return 'structured_observation_not_in_description'
        if requirement and normalize(requirement) not in normalize(row['description']):
            return 'structured_requirement_not_in_description'
    return ''


def build(source,output):
    if output.exists():raise FileExistsError('Use a new dataset directory')
    taxonomy,_=catalog();codes=list(taxonomy)
    with ZipFile(source) as archive:
        manifest={r['scenario_id']:r for r in map(json.loads,archive.read('scenario_manifest.jsonl').splitlines())}
        splits={name:list(map(json.loads,archive.read(name+'.jsonl').splitlines())) for name in ('train','validation')}
        fit={(normalize(r['description']),tuple(r['expected_codes'])) for r in map(json.loads,archive.read('train_fit.jsonl').splitlines())}
        archive_hash=sha256(source.read_bytes()).hexdigest()
    excluded=[];outputs={};families={};full_texts={}
    for split,rows in splits.items():
        current=[];families[split]=set();full_texts[split]=set()
        # Audit the English rendering first, then quarantine all translations of
        # a scenario when its structured claim is absent from the actual text.
        problems={}
        for row in rows:
            if row['expected_decision']=='accept' and row['language']=='en':
                issue=audit_positive(row,manifest[row['scenario_id']])
                if issue:problems[row['scenario_id']]=issue
        def add(row,code,state,kind,text=None):
            scenario=manifest[row['scenario_id']]
            current.append({'example_id':f"{row['scenario_id']}:{row['language']}:{code}:{kind}",
                'source_id':row['scenario_id'],'family_ids':scenario['evidence_family_ids'],
                'split':'fit' if split=='train' else 'validation','language':row['language'],
                'description':text or row['description'],'target_code':code,'evidence_state':state,
                'label_origin':'supplied_structured_synthetic_scenario' if kind in {'original','unrelated_target'} else 'explicit_training_counterfactual',
                'kind':kind,'source_expected_codes':row['expected_codes'],
                'audit_status':'structured_annotation_audit_not_independent_human_gold'})
        for row in rows:
            scenario=manifest[row['scenario_id']]
            if row['expected_decision']=='accept':
                issue=problems.get(row['scenario_id']) or audit_positive(row,scenario)
                if issue:
                    excluded.append({'source_id':row['scenario_id'],'language':row['language'],'split':split,'reason':issue});continue
                code=row['expected_codes'][0]
                if split=='train' and (normalize(row['description']),tuple(row['expected_codes'])) not in fit:
                    raise ValueError('Positive fit row absent from original train_fit')
                add(row,code,'supported','original')
                # Orthogonal category controls do not assert that the observed
                # incident complies; it contains no evidence for this target.
                index=codes.index(code)
                for offset in (9,17):
                    target=codes[(index+offset)%len(codes)]
                    add(row,target,'insufficient','unrelated_target')
                if split=='train':
                    lang=row['language'];text=row['description']
                    uncertain={
                        'en':f'Unverified allegation, not an observed finding: [{text}] The report has not been confirmed.',
                        'fil':f'Hindi beripikadong ulat lamang, hindi aktuwal na obserbasyon: [{text}] Hindi pa kinukumpirma ang ulat.',
                        'taglish':f'Unconfirmed report lang, hindi observed finding: [{text}] Hindi pa verified ang report.',
                    }[lang]
                    compliant={
                        'en':f'The inspector checked the applicable condition and confirmed compliance. The following allegation was checked and disproved: [{text}] This was not an observed violation.',
                        'fil':f'Sinuri ng inspektor ang nauukol na kondisyon at kinumpirmang nasunod ito. Sinuri at pinabulaanan ang sumusunod na ulat: [{text}] Walang ganitong naobserbahang paglabag.',
                        'taglish':f'Inspector checked the applicable condition and confirmed compliant. Na-check at disproved ang allegation na ito: [{text}] Hindi ito observed violation.',
                    }[lang]
                    add(row,code,'insufficient','unconfirmed_counterfactual',uncertain)
                    add(row,code,'compliant','checked_compliance_counterfactual',compliant)
            else:
                topic=scenario['evidence_family_ids'][0].split('|')[-1]
                match=re.match(r'(\d{2})-',topic)
                state='compliant' if row['scenario_subtype']=='explicit_compliance' else 'insufficient'
                targets=[codes[int(match[1])-1]] if match else [codes[i] for i in (2,10,23)]
                for code in targets:add(row,code,state,'original')
            families[split].update(scenario['evidence_family_ids'])
            full_texts[split].add(normalize(row['description']))
        # Deduplicate inputs while rejecting contradictory labels. Retain all
        # source family IDs for lineage instead of choosing one duplicate.
        dedup={}
        for example in current:
            key=(normalize(example['description']),example['target_code'])
            if key in dedup:
                if dedup[key]['evidence_state']!=example['evidence_state']:raise ValueError('Conflicting evidence labels')
                dedup[key]['family_ids']=sorted(set(dedup[key]['family_ids'])|set(example['family_ids']))
            else:dedup[key]=example
        outputs[split]=list(dedup.values())
    if families['train']&families['validation'] or full_texts['train']&full_texts['validation']:
        raise ValueError('Family or original-description leakage')
    fit_inputs={(normalize(r['description']),r['target_code']) for r in outputs['train']}
    if any((normalize(r['description']),r['target_code']) in fit_inputs for r in outputs['validation']):
        raise ValueError('Verifier input overlap')
    output.mkdir(parents=True)
    for split,rows in outputs.items():
        name='fit' if split=='train' else 'validation'
        (output/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    report={'source':str(source),'source_sha256':archive_hash,'states':STATES,
        'method':'Single-incident source scenarios only. No multi-label sentence inheritance. Fitting uses original train partition; validation uses original validation partition. Structured observations are annotation/audit metadata, never model inputs.',
        'independence':'Synthetic development labels and explicit fit-only counterfactuals; not independent operational gold.',
        'split_counts':{s:{'examples':len(rs),'states':dict(Counter(r['evidence_state'] for r in rs)),
            'kinds':dict(Counter(r['kind'] for r in rs)),'families':len(families[s]),
            'original_positive_support':dict(Counter(r['target_code'] for r in rs if r['evidence_state']=='supported'))} for s,rs in outputs.items()},
        'leakage_checks':{'shared_families':0,'shared_original_descriptions':0,'shared_model_inputs':0},
        'exclusions':excluded,'exclusion_counts':dict(Counter(r['reason'] for r in excluded)),
        'operational_csv_usage':'The inspected 150-record market CSV remains development regression data and is not used to fit or select this verifier cutoff.',
        'test_usage':'No test descriptions or evaluation results are read. Test manifest entries are not used to fit or select cutoffs.'}
    (output/'audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('split_counts','leakage_checks','exclusion_counts')},indent=2),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=Path.home()/'Downloads/marikina_synthetic_dataset_v2.zip')
    p.add_argument('--output',type=Path,default=ROOT/'data/evidence-v1')
    a=p.parse_args();build(a.source,a.output)
