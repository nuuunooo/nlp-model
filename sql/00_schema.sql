-- Recommendation schema for a development copy of the PostgreSQL 18 handoff.
-- Depends on the existing public.tickets, ordinances, market_sections, vendor_profiles.
-- DO NOT import synthetic sample records into the real ticket tables.
BEGIN;
CREATE TABLE IF NOT EXISTS public.inspections (
  id bigserial PRIMARY KEY,
  vendor_id integer NOT NULL REFERENCES public.vendor_profiles(id),
  market_section_id integer NOT NULL REFERENCES public.market_sections(id),
  enforcer_id integer,
  inspected_at timestamptz NOT NULL DEFAULT now(),
  outcome text NOT NULL CHECK (outcome IN ('clean','flagged')),
  linked_ticket_id integer REFERENCES public.tickets(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inspections_section_time ON public.inspections(market_section_id,inspected_at);

CREATE TABLE IF NOT EXISTS public.nlp_verified_reweighs (
 ticket_id integer PRIMARY KEY REFERENCES public.tickets(id) ON DELETE CASCADE,
 description_hash bytea NOT NULL,
 declared_grams numeric NOT NULL CHECK (declared_grams > 0 AND declared_grams < 'Infinity'::numeric),
 measured_grams numeric NOT NULL CHECK (measured_grams > 0 AND measured_grams < 'Infinity'::numeric),
 evidence_reference text NOT NULL CHECK (btrim(evidence_reference) <> ''),
 verified_by integer NOT NULL CHECK (verified_by > 0),
 verified_at timestamptz NOT NULL DEFAULT now(),
 revision bigint NOT NULL DEFAULT 1,
 revoked boolean NOT NULL DEFAULT false,
 needs_processing boolean NOT NULL DEFAULT true
);
ALTER TABLE public.nlp_verified_reweighs ADD COLUMN IF NOT EXISTS scale_check_reference text;
ALTER TABLE public.nlp_verified_reweighs ADD COLUMN IF NOT EXISTS transaction_verified boolean NOT NULL DEFAULT false;
ALTER TABLE public.nlp_verified_reweighs ADD COLUMN IF NOT EXISTS conditions_verified boolean NOT NULL DEFAULT false;
ALTER TABLE public.nlp_verified_reweighs ADD COLUMN IF NOT EXISTS evidence_issue text;
CREATE INDEX IF NOT EXISTS idx_reweighs_needing_processing
 ON public.nlp_verified_reweighs(ticket_id) WHERE needs_processing;

CREATE TABLE IF NOT EXISTS public.nlp_violation_taxonomy (
 code text PRIMARY KEY,
 ordinance_id integer REFERENCES public.ordinances(id),
 ordinance_category text NOT NULL,
 name_en text NOT NULL,
 name_tl text,
 severity smallint NOT NULL CHECK (severity BETWEEN 1 AND 3),
 action_template_en text NOT NULL,
 evidence_requirement_en text,
 is_active boolean NOT NULL DEFAULT true
);
ALTER TABLE public.nlp_violation_taxonomy ALTER COLUMN ordinance_id DROP NOT NULL;
ALTER TABLE public.nlp_violation_taxonomy ADD COLUMN IF NOT EXISTS evidence_requirement_en text;
CREATE TABLE IF NOT EXISTS public.nlp_lexicon_terms (
 id bigserial PRIMARY KEY,
 code text NOT NULL REFERENCES public.nlp_violation_taxonomy(code),
 pattern text NOT NULL,
 confidence numeric(4,3) NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 negatable boolean NOT NULL DEFAULT true,
 notes text,
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(code,pattern)
);
CREATE TABLE IF NOT EXISTS public.nlp_ticket_text (
 ticket_id integer PRIMARY KEY REFERENCES public.tickets(id) ON DELETE CASCADE,
 clean_text text NOT NULL,
 language text NOT NULL,
 char_count integer NOT NULL,
 status text NOT NULL CHECK(status IN ('labeled','review','no_signal','clear','junk','empty','duplicate')),
 review_reason text,
 pipeline_version text NOT NULL,
 description_hash bytea,
 processed_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.nlp_ticket_text ADD COLUMN IF NOT EXISTS description_hash bytea;
CREATE TABLE IF NOT EXISTS public.nlp_violation_mentions (
 ticket_id integer NOT NULL REFERENCES public.tickets(id) ON DELETE CASCADE,
 code text NOT NULL REFERENCES public.nlp_violation_taxonomy(code),
 evidence_span text NOT NULL,
 confidence numeric(4,3) NOT NULL CHECK(confidence BETWEEN 0 AND 1),
 detection_source text NOT NULL CHECK(detection_source IN ('rule','model','llm','human')),
 review_status text NOT NULL DEFAULT 'pending' CHECK(review_status IN ('accepted','pending','confirmed','rejected')),
 reweigh_revision bigint,
 reviewed_by integer,
 reviewed_at timestamptz,
 processed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(ticket_id,code)
);
ALTER TABLE public.nlp_violation_mentions ADD COLUMN IF NOT EXISTS reweigh_revision bigint;
CREATE INDEX IF NOT EXISTS idx_mentions_code_status ON public.nlp_violation_mentions(code,review_status);
CREATE OR REPLACE VIEW public.nlp_current_description_findings AS
 SELECT m.ticket_id,m.code,t.market_section_id,t.issued_at
 FROM public.nlp_violation_mentions m
 JOIN public.tickets t ON t.id=m.ticket_id
 JOIN public.nlp_ticket_text n ON n.ticket_id=m.ticket_id
 WHERE m.review_status='accepted' AND n.status='labeled'
   AND n.pipeline_version='3.3.0-description-only'
   AND n.description_hash=sha256(convert_to(t.description,'UTF8'))
   AND lower(coalesce(t.status,'')) <> 'void';
CREATE OR REPLACE VIEW public.nlp_current_weight_findings AS
 SELECT ticket_id,market_section_id,issued_at FROM public.nlp_current_description_findings
 WHERE code='WeightMeasures';
CREATE TABLE IF NOT EXISTS public.nlp_review_queue (
 ticket_id integer PRIMARY KEY REFERENCES public.tickets(id) ON DELETE CASCADE,
 proposed_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
 reason text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected')),
 reviewer_id integer,
 reviewed_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.nlp_section_insights (
 section_id integer NOT NULL REFERENCES public.market_sections(id),
 window_days smallint NOT NULL DEFAULT 30,
 prominent_code text REFERENCES public.nlp_violation_taxonomy(code),
 prominent_violation text,
 recommended_action text,
 ticket_mentions integer NOT NULL DEFAULT 0,
 inspections_sampled integer NOT NULL DEFAULT 0,
 peak_time text,
 pattern_confidence text NOT NULL,
 risk_score numeric(10,2) NOT NULL DEFAULT 0,
 risk_level text NOT NULL,
 last_flagged timestamptz,
 computed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(section_id,window_days)
);
CREATE TABLE IF NOT EXISTS public.nlp_recommendations (
 id bigserial PRIMARY KEY,
 section_id integer NOT NULL REFERENCES public.market_sections(id),
 code text NOT NULL REFERENCES public.nlp_violation_taxonomy(code),
 action_text text NOT NULL,
 priority_rank integer NOT NULL,
 risk_score numeric(10,2) NOT NULL,
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','assigned','completed','dismissed','stale')),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(section_id,code)
);
CREATE TABLE IF NOT EXISTS public.nlp_ingest_state (
 worker_key text PRIMARY KEY,
 last_updated_at timestamptz NOT NULL DEFAULT '1970-01-01 00:00:00+00'::timestamptz,
 last_ticket_id integer NOT NULL DEFAULT 0,
 processed_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO public.nlp_ingest_state(worker_key) VALUES ('tickets') ON CONFLICT(worker_key) DO NOTHING;
COMMIT;
