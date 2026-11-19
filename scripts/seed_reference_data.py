"""Seed taxonomy and regex lexicon in the SQL schema without modifying live tickets."""
from pathlib import Path
import sys,os
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import catalog

LEGACY_CODES = [
    'OB-01', 'OB-02', 'OB-03', 'NO-01', 'NO-02', 'LI-01', 'LI-02', 'LI-03',
    'SA-01', 'SA-02', 'WM-01', 'WM-02', 'WM-03',
]

def seed(conn):
    taxonomy, lexicon = catalog()
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(40017201)')
        for x in taxonomy.values():
            conn.execute('''INSERT INTO public.nlp_violation_taxonomy
              (code,ordinance_id,ordinance_category,name_en,name_tl,severity,action_template_en,evidence_requirement_en)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(code) DO UPDATE SET ordinance_id=EXCLUDED.ordinance_id,
              ordinance_category=EXCLUDED.ordinance_category,name_en=EXCLUDED.name_en,name_tl=EXCLUDED.name_tl,
              severity=EXCLUDED.severity,action_template_en=EXCLUDED.action_template_en,
              evidence_requirement_en=EXCLUDED.evidence_requirement_en,is_active=true''',
              (x['code'], x['ordinance_id'] or None, x['ordinance_category'], x['name_en'],
               x['name_tl'], int(x['severity']), x['action_template_en'], x['evidence_requirement_en']))
        conn.execute('UPDATE public.nlp_violation_taxonomy SET is_active=false WHERE code=ANY(%s)', (LEGACY_CODES,))
        for x in lexicon:
            conn.execute('''INSERT INTO public.nlp_lexicon_terms(code,pattern,confidence,negatable,notes)
             VALUES (%s,%s,%s,%s,%s) ON CONFLICT(code,pattern) DO UPDATE SET
             confidence=EXCLUDED.confidence,negatable=EXCLUDED.negatable,notes=EXCLUDED.notes''',
             (x['code'],x['pattern'],float(x['confidence']),x['negatable'].lower()=='true',x['notes']))
    return len(taxonomy)

if __name__=='__main__':
    try:import psycopg
    except ImportError:raise SystemExit('Install: pip install "psycopg[binary]"')
    url=os.getenv('DATABASE_URL')
    if not url:raise SystemExit('Set DATABASE_URL; no DB changes made')
    with psycopg.connect(url) as c:
        count = seed(c)
    print(f'Seeded {count} taxonomy codes and lexicon patterns.')
