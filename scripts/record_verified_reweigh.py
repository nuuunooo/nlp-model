"""Record or revoke a reference-scale check from a separate inspection record."""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.reweigh import MASS_UNITS, mass_in_grams, description_evidence_issue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Record or replace the current verified reweigh")
    record.add_argument("ticket_id", type=int)
    record.add_argument("declared")
    record.add_argument("declared_unit", choices=MASS_UNITS)
    record.add_argument("measured")
    record.add_argument("measured_unit", choices=MASS_UNITS)
    record.add_argument("--verified-by", type=int, required=True)
    record.add_argument("--reference", required=True, help="ID of the independent reference-scale record")
    record.add_argument("--scale-check-reference", help="Record verifying the reference scale worked at the reweigh")
    record.add_argument("--transaction-verified", action="store_true",
                        help="The declared quantity and measured item belong to the same verified sale")
    record.add_argument("--conditions-verified", action="store_true",
                        help="Tare, packaging, ice, water and other relevant weighing conditions were resolved")
    revoke = commands.add_parser("revoke", help="Withdraw the current verified reweigh")
    revoke.add_argument("ticket_id", type=int)
    args = parser.parse_args()

    if args.command == "record":
        try:
            declared = mass_in_grams(args.declared, args.declared_unit)
            measured = mass_in_grams(args.measured, args.measured_unit)
        except ValueError as exc:
            parser.error(str(exc))
        reference = args.reference.strip()
        if not reference or args.verified_by <= 0:
            parser.error("A verifier ID and independent evidence reference are required")

    url = os.getenv("DATABASE_URL")
    if not url:
        parser.error("Set DATABASE_URL first")
    import psycopg

    with psycopg.connect(url) as conn:
        # Serialize evidence changes with ingestion and recommendation refresh.
        conn.execute("SELECT pg_advisory_xact_lock(40017201)")
        if args.command == "revoke":
            changed = conn.execute("""
                UPDATE public.nlp_verified_reweighs
                SET revoked=true, needs_processing=true, revision=revision+1
                WHERE ticket_id=%s AND NOT revoked
            """, (args.ticket_id,)).rowcount
        else:
            ticket = conn.execute("""
                SELECT sha256(convert_to(description,'UTF8')), description FROM public.tickets
                WHERE id=%s AND lower(coalesce(status,'')) <> 'void'
                FOR SHARE
            """, (args.ticket_id,)).fetchone()
            if ticket is None:
                parser.error("The ticket must exist and be active")
            evidence_issue = description_evidence_issue(ticket[1])
            changed = conn.execute("""
                INSERT INTO public.nlp_verified_reweighs AS e
                    (ticket_id, description_hash, declared_grams, measured_grams,
                     evidence_reference, verified_by, scale_check_reference,
                     transaction_verified, conditions_verified, evidence_issue)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(ticket_id) DO UPDATE SET
                    description_hash=EXCLUDED.description_hash, declared_grams=EXCLUDED.declared_grams,
                    measured_grams=EXCLUDED.measured_grams, evidence_reference=EXCLUDED.evidence_reference,
                    verified_by=EXCLUDED.verified_by, verified_at=now(),
                    scale_check_reference=EXCLUDED.scale_check_reference,
                    transaction_verified=EXCLUDED.transaction_verified,
                    conditions_verified=EXCLUDED.conditions_verified, evidence_issue=EXCLUDED.evidence_issue,
                    revision=e.revision+1, revoked=false, needs_processing=true
                WHERE e.revoked OR (e.description_hash, e.declared_grams, e.measured_grams,
                    e.evidence_reference, e.verified_by, e.scale_check_reference,
                    e.transaction_verified, e.conditions_verified, e.evidence_issue) IS DISTINCT FROM
                    (EXCLUDED.description_hash, EXCLUDED.declared_grams, EXCLUDED.measured_grams,
                     EXCLUDED.evidence_reference, EXCLUDED.verified_by, EXCLUDED.scale_check_reference,
                     EXCLUDED.transaction_verified, EXCLUDED.conditions_verified, EXCLUDED.evidence_issue)
            """, (args.ticket_id, ticket[0], declared, measured, reference, args.verified_by,
                  (args.scale_check_reference or "").strip() or None,
                  args.transaction_verified, args.conditions_verified, evidence_issue)).rowcount
    print("Updated verified reweigh. The next worker run will refresh the ticket." if changed
          else "No reweigh change was needed.")


if __name__ == "__main__":
    main()
