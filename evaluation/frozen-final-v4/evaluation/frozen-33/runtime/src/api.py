"""Read-only dashboard API. Must be placed BEHIND existing admin authentication before deployment."""
import os
from fastapi import FastAPI,HTTPException
app=FastAPI(title='Marikina NLP insights API (internal/admin only)',docs_url=None,redoc_url=None)

def select(sql,params=()):
    import psycopg
    from psycopg.rows import dict_row
    url=os.getenv('DATABASE_URL')
    if not url:raise HTTPException(503,'DATABASE_URL not configured')
    with psycopg.connect(url,row_factory=dict_row) as db:
        return db.execute(sql,params).fetchall()

@app.get('/internal/nlp/section-insights')
def section_insights():
    return select('''SELECT s.section_id,ms.name AS section_name,s.prominent_code,s.prominent_violation,
         s.recommended_action,s.ticket_mentions,s.inspections_sampled,s.peak_time,
         s.pattern_confidence,s.risk_score,s.risk_level,s.last_flagged,s.computed_at
         FROM public.nlp_section_insights s JOIN public.market_sections ms ON ms.id=s.section_id
         LEFT JOIN public.nlp_violation_taxonomy v ON v.code=s.prominent_code
         WHERE s.window_days=30 AND (s.prominent_code IS NULL OR v.is_active)
         AND (s.prominent_code IS NULL OR EXISTS (
             SELECT 1 FROM public.nlp_current_description_findings w WHERE w.market_section_id=s.section_id AND w.code=s.prominent_code
             AND w.issued_at BETWEEN now()-interval '30 days' AND now()
         ))
         ORDER BY s.risk_score DESC,ms.name''')

@app.get('/internal/nlp/recommendations')
def recommendations():
    return select('''SELECT r.id,ms.name AS section_name,r.code,r.action_text,r.priority_rank,
              r.risk_score,r.status,r.updated_at
              FROM public.nlp_recommendations r JOIN public.market_sections ms ON ms.id=r.section_id
              JOIN public.nlp_violation_taxonomy v ON v.code=r.code
              WHERE v.is_active AND r.status IN ('active','assigned')
              AND EXISTS (
                  SELECT 1 FROM public.nlp_current_description_findings w WHERE w.market_section_id=r.section_id AND w.code=r.code
                  AND w.issued_at BETWEEN now()-interval '30 days' AND now()
              )
              ORDER BY r.priority_rank,r.id''')

@app.get('/internal/nlp/review-queue')
def review_queue():
    # Compatibility route for existing dashboard clients.
    return []
