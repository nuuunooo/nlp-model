"""Supervisor CLI for human-reviewed labels (not an unauthenticated web endpoint).

Example:
 DATABASE_URL=... python scripts/confirm_review.py 123 'Vendor Identification,Sanitation' 7
For no violation after review: use '-' as the code list.
"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import catalog, normalize

def main():
    if len(sys.argv)!=4:
        raise SystemExit("Usage: python scripts/confirm_review.py TICKET_ID 'CODE1,CODE2' REVIEWER_ID")
    ticket_id=int(sys.argv[1]); reviewer_id=int(sys.argv[3])
    taxonomy,_=catalog()
    canonical = {code.casefold(): code for code in taxonomy}
    requested = [] if sys.argv[2].strip() == '-' else [x.strip() for x in sys.argv[2].split(',')]
    codes = sorted({canonical.get(code.casefold(), code) for code in requested})
    unknown=set(codes)-set(taxonomy)
    if unknown:raise SystemExit('Unknown code(s): '+repr(sorted(unknown))+'. Add approved taxonomy first.')
    url=os.getenv('DATABASE_URL')
    if not url:raise SystemExit('DATABASE_URL is required')
    try:import psycopg
    except ImportError:raise SystemExit('Install psycopg first')
    from psycopg.rows import dict_row
    with psycopg.connect(url,row_factory=dict_row,autocommit=True) as conn:
      with conn.transaction():
        ticket=conn.execute('''SELECT n.clean_text,t.description FROM public.nlp_ticket_text n
            JOIN public.tickets t ON t.id=n.ticket_id WHERE n.ticket_id=%s
            FOR UPDATE OF n''',(ticket_id,)).fetchone()
        queue=conn.execute('SELECT status FROM public.nlp_review_queue WHERE ticket_id=%s FOR UPDATE',(ticket_id,)).fetchone()
        if not ticket or not queue or queue['status']!='pending':
            raise SystemExit('Ticket is not in a pending review queue; nothing changed.')
        if normalize(ticket['description']) != ticket['clean_text']:
            raise SystemExit('The ticket description has changed. Refresh ingestion before confirming it.')
        conn.execute('DELETE FROM public.nlp_violation_mentions WHERE ticket_id=%s',(ticket_id,))
        for code in codes:
            conn.execute('''INSERT INTO public.nlp_violation_mentions
                (ticket_id,code,evidence_span,confidence,detection_source,review_status,reviewed_by,reviewed_at)
                VALUES (%s,%s,%s,1.0,'human','confirmed',%s,now())''',
                (ticket_id,code,ticket['clean_text'][:200],reviewer_id))
        conn.execute("UPDATE public.nlp_ticket_text SET status=%s,review_reason='human-reviewed',processed_at=now() WHERE ticket_id=%s",
                     ('labeled' if codes else 'clear',ticket_id))
        conn.execute('''UPDATE public.nlp_review_queue SET status='confirmed',proposed_codes=%s,
            reviewer_id=%s,reviewed_at=now(),updated_at=now() WHERE ticket_id=%s''',
            (codes,reviewer_id,ticket_id))
    print('Supervisor-reviewed labels saved. Next ingestion run refreshes recommendations.')
if __name__=='__main__':main()
