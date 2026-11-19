"""PostgreSQL ingestion worker for the supplied Marikina database.

Usage: DATABASE_URL=... python -m src.db_runner
Run periodically (e.g. every 5 minutes using Windows Task Scheduler or cron).
Each batch + watermark commits atomically. Does not modify original tickets.
"""
import argparse
import os
from hashlib import sha256
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .engine import catalog, analyze_ticket, summarize_sections

MARKET_TIME = timezone(timedelta(hours=8))

BATCH_SIZE=250
QUERY='''
 SELECT t.id AS ticket_id, t.vendor_id, t.market_section_id AS section_id,
        t.type AS ticket_type, t.description, t.issued_at, t.updated_at,
        COALESCE(
         (SELECT string_agg(x.ordinance_id::text,'|' ORDER BY x.ordinance_id)
          FROM (SELECT DISTINCT ordinance_id FROM public.ticket_violations WHERE ticket_id=t.id) x),
         array_to_string(t.categories,'|'), '') AS structured_ordinance_ids
 FROM public.tickets t
 WHERE (t.updated_at,t.id) > (%s::timestamptz,%s::integer)
 ORDER BY t.updated_at,t.id LIMIT %s
'''

def get_fallbacks(taxonomy):
    clf=llm=None
    setfit_path = os.getenv('SETFIT_MODEL_DIR', '').strip()
    cp=os.getenv('CLASSIFIER_PATH','').strip()
    if setfit_path:
        from .setfit_classifier import SetFitClassifier
        clf = SetFitClassifier(setfit_path, taxonomy)
    elif cp and Path(cp).is_file():
        from .classifier import TrainedClassifier
        clf=TrainedClassifier(cp)
        if not set(clf.bundle['codes']).issubset(taxonomy):
            raise ValueError('CLASSIFIER_PATH contains labels outside the action taxonomy')
    if os.getenv('OLLAMA_ENABLED','false').lower()=='true':
        from .llm import OllamaFallback
        llm=OllamaFallback(os.getenv('OLLAMA_MODEL','qwen2.5:7b'),os.getenv('OLLAMA_URL','http://127.0.0.1:11434'))
    return clf,llm

def write_batch(conn,records,taxonomy,lexicon,clf,llm):
    texts,mentions,queues=[],[],[]
    with conn.transaction():
        for row in records:
            item={key: (val.isoformat() if isinstance(val,datetime) else val) for key,val in row.items()}
            clean,hits=analyze_ticket(item,taxonomy,lexicon,clf,llm)
            # Suppress genuine same-vendor/same-day/identical-description duplicates
            # across batches, using a smaller ticket ID as canonical.
            duplicate = bool(clean['clean_text'] and conn.execute('''
                SELECT 1 FROM public.nlp_ticket_text n
                JOIN public.tickets old ON old.id=n.ticket_id
                WHERE old.vendor_id=%s
                  AND (old.issued_at AT TIME ZONE 'Asia/Manila')::date =
                      (%s::timestamptz AT TIME ZONE 'Asia/Manila')::date
                  AND old.id<%s AND n.clean_text=%s LIMIT 1''',
                (row['vendor_id'],row['issued_at'],row['ticket_id'],clean['clean_text'])).fetchone())
            if duplicate:
                clean['status']='duplicate'
                clean['codes']=''
                clean['review_reason']='same_vendor_same_day_same_text'
                hits=[]
            texts.append(clean);mentions.extend(hits)
            conn.execute('''INSERT INTO public.nlp_ticket_text
                (ticket_id,clean_text,language,char_count,status,review_reason,pipeline_version,description_hash,processed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(ticket_id) DO UPDATE SET clean_text=EXCLUDED.clean_text,
                language=EXCLUDED.language,char_count=EXCLUDED.char_count,status=EXCLUDED.status,
                review_reason=EXCLUDED.review_reason,pipeline_version=EXCLUDED.pipeline_version,
                description_hash=EXCLUDED.description_hash,processed_at=now()''',
                (row['ticket_id'],clean['clean_text'],clean['language'],clean['raw_char_count'],
                 clean['status'],clean['review_reason'],clean['pipeline_version'],
                 sha256(str(row['description'] or '').encode('utf-8')).digest()))
            conn.execute('DELETE FROM public.nlp_violation_mentions WHERE ticket_id=%s',(row['ticket_id'],))
            for m in hits:
                conn.execute('''INSERT INTO public.nlp_violation_mentions
                   (ticket_id,code,evidence_span,confidence,detection_source,review_status)
                   VALUES (%s,%s,%s,%s,%s,%s)''',
                   (row['ticket_id'],m['code'],m['evidence'],m['confidence'],m['source'],m['review_status']))
            conn.execute("DELETE FROM public.nlp_review_queue WHERE ticket_id=%s AND status='pending'",
                         (row['ticket_id'],))
        last=records[-1]
        conn.execute('''UPDATE public.nlp_ingest_state SET
            last_updated_at=%s,last_ticket_id=%s,processed_at=now()
            WHERE worker_key='tickets' AND (last_updated_at,last_ticket_id) < (%s,%s) ''',
            (last['updated_at'],last['ticket_id'],last['updated_at'],last['ticket_id']))
    return len(texts),len(mentions),len(queues)

def rebuild_insights(conn,taxonomy):
    now=datetime.now(timezone.utc)
    start=now-timedelta(days=30)
    accepted=conn.execute('''SELECT w.ticket_id,w.code,'accepted' AS review_status,
         t.market_section_id AS section_id,t.vendor_id,t.type AS ticket_type,t.issued_at
         FROM public.nlp_current_description_findings w JOIN public.tickets t ON t.id=w.ticket_id
         WHERE w.code=ANY(%s) AND t.issued_at BETWEEN %s AND %s''',
         (list(taxonomy),start,now)).fetchall()
    visits=conn.execute('''SELECT id AS inspection_id, market_section_id AS section_id, inspected_at
         FROM public.inspections WHERE inspected_at BETWEEN %s AND %s''',(start,now)).fetchall()
    sections=conn.execute('SELECT id AS section_id,name AS section_name FROM public.market_sections ORDER BY id').fetchall()
    def iso(r):
        return {k: (v.astimezone(MARKET_TIME).isoformat() if isinstance(v,datetime) else v) for k,v in r.items()}
    insights=summarize_sections([iso(r) for r in accepted],[iso(r) for r in visits],
                 taxonomy,[iso(r) for r in sections],period_days=30,anchor=now)
    with conn.transaction():
        for rank,item in enumerate(insights,1):
            conn.execute('''INSERT INTO public.nlp_section_insights
                (section_id,window_days,prominent_code,prominent_violation,recommended_action,ticket_mentions,
                 inspections_sampled,peak_time,pattern_confidence,risk_score,risk_level,last_flagged,computed_at)
                VALUES (%s,30,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(section_id,window_days) DO UPDATE SET
                 prominent_code=EXCLUDED.prominent_code,prominent_violation=EXCLUDED.prominent_violation,
                 recommended_action=EXCLUDED.recommended_action,ticket_mentions=EXCLUDED.ticket_mentions,
                 inspections_sampled=EXCLUDED.inspections_sampled,peak_time=EXCLUDED.peak_time,
                 pattern_confidence=EXCLUDED.pattern_confidence,risk_score=EXCLUDED.risk_score,
                 risk_level=EXCLUDED.risk_level,last_flagged=EXCLUDED.last_flagged,computed_at=now()''',
                 (item['section_id'],item['prominent_code'] or None,item['prominent_violation'] or None,
                  item['recommended_action'] or None,item['ticket_mentions'],item['inspections_sampled'],
                  item['peak_time'] or None,item['pattern_confidence'],item['risk_score'],item['risk_level'],
                  item['last_flagged'] or None))
            # Stale unassigned recommendations are not displayed as current.
            conn.execute('''UPDATE public.nlp_recommendations SET status='stale',updated_at=now()
              WHERE section_id=%s AND code<>%s AND status IN ('active','assigned') ''',
              (item['section_id'],item['prominent_code'] or '__NONE__'))
            if item['prominent_code']:
                conn.execute('''INSERT INTO public.nlp_recommendations
                   (section_id,code,action_text,priority_rank,risk_score,status)
                   VALUES (%s,%s,%s,%s,%s,'active')
                   ON CONFLICT(section_id,code) DO UPDATE SET
                   action_text=EXCLUDED.action_text,priority_rank=EXCLUDED.priority_rank,
                   risk_score=EXCLUDED.risk_score,updated_at=now(),
                   status=CASE WHEN public.nlp_recommendations.status='stale' THEN 'active'
                               ELSE public.nlp_recommendations.status END''',
                   (item['section_id'],item['prominent_code'],item['recommended_action'],rank,item['risk_score']))
    return insights

def main():
    parser = argparse.ArgumentParser(description="Refresh market violation recommendations")
    parser.add_argument("--reprocess", action="store_true", help="Revisit existing tickets with the configured model")
    args = parser.parse_args()
    url=os.getenv('DATABASE_URL')
    if not url:raise SystemExit('Set DATABASE_URL first. No DB modifications performed.')
    try:import psycopg
    except ImportError:raise SystemExit('Install psycopg: pip install "psycopg[binary]"')
    from psycopg.rows import dict_row
    tax,lex=catalog()
    clf,llm=get_fallbacks(tax)
    with psycopg.connect(url,row_factory=dict_row,autocommit=True) as conn:
        # Prevent overlapping workers from processing the same watermark concurrently.
        with conn.transaction():
            locked=conn.execute("SELECT pg_try_advisory_xact_lock(40017201) AS acquired").fetchone()['acquired']
            if not locked:raise SystemExit('Another worker is running')
            # Hold lock across the whole run by session lock (released automatically on close).
            got=conn.execute('SELECT pg_try_advisory_lock(40017201) AS acquired').fetchone()['acquired']
            if not got:raise SystemExit('Another worker is running')
        n=0
        st=conn.execute("SELECT last_updated_at,last_ticket_id FROM public.nlp_ingest_state WHERE worker_key='tickets'").fetchone()
        if st is None:raise RuntimeError('Run sql/00_schema.sql before ingestion')
        cursor = (st['last_updated_at'],st['last_ticket_id'])
        if args.reprocess:
            cursor = ('-infinity', 0)
        while True:
            batch=conn.execute(QUERY,(*cursor,BATCH_SIZE)).fetchall()
            if not batch:break
            a,b,c=write_batch(conn,batch,tax,lex,clf,llm)
            n+=a;print(f'Processed {a} tickets with {b} automatic findings')
            cursor = (batch[-1]['updated_at'], batch[-1]['ticket_id'])
            if len(batch)<BATCH_SIZE:break
        insights=rebuild_insights(conn,tax)
        print(f'Processed {n} changed ticket(s). Refreshed {len(insights)} market sections.')
if __name__=='__main__':main()
