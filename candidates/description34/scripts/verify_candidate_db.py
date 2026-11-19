"""Exercise candidate worker/API using temporary fixtures in the isolated dev DB."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
from time import sleep
from urllib.request import urlopen
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import uvicorn

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.api import app
from src.db_runner import rebuild_insights
from src.engine import catalog,RULE_PIPELINE_VERSION


def dashboard():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        base=f'http://127.0.0.1:{sock.getsockname()[1]}/internal/nlp/'
        server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
        thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                sleep(.05)
            else:raise RuntimeError('Local API did not start')
            output={}
            for route in ('recommendations','section-insights','review-queue'):
                with urlopen(base+route,timeout=5) as response:
                    assert response.status==200
                    output[route]=json.load(response)
            return output
        finally:
            server.should_exit=True;thread.join(6)


def main():
    if RULE_PIPELINE_VERSION!='3.4.0-candidate':raise ValueError('Run from the candidate checkout')
    cases={
        'short_mass':('Fish sold as 1 kg, measured at 840 g on the reference scale.',{'WeightMeasures'}),
        'scale_seal':('The vendor scale has no City Treasury registration seal.',{'WeightMeasures'}),
        'multi':('Cook has no health certificate; the vendor scale has no City Treasury registration seal; stacked crates fully block the fire exit.',{'Permit & Licensing','WeightMeasures','Obstruction'}),
        'compliant':('Business permit current and posted; garbage in sealed bags; daily fee paid, receipt shown.',set()),
        'uncertain':('May tsismis na walang permit, hindi na-verify.',set()),
        'duty_unknown':('Light in the stall flickering, maintenance duty unknown.',set()),
        'qualified':('Vendor had no vendor ID; crates blocked the exit. Neither claim was confirmed.',set()),
    }
    prefix='CAND34-'+uuid4().hex[:10]+'-'
    ids={};section=None
    with psycopg.connect(os.environ['DATABASE_URL'],row_factory=dict_row,autocommit=True) as conn:
        try:
            for name,(text,expected) in cases.items():
                row=conn.execute('''INSERT INTO public.tickets
                    (control_number,vendor_id,market_section_id,enforcer_id,type,status,description,categories,issued_at,updated_at)
                    SELECT %s,vendor_id,(SELECT id FROM public.market_sections ORDER BY id DESC LIMIT 1),
                           enforcer_id,'Ticket','Issued',%s,ARRAY[]::integer[],now(),now()
                    FROM public.tickets ORDER BY id LIMIT 1 RETURNING id,market_section_id''',
                    (prefix+name,text+' Dev fixture '+prefix+'.')).fetchone()
                if row is None:raise ValueError('Isolated DB needs the existing development reference ticket')
                ids[name]=row['id'];section=row['market_section_id']
            subprocess.run([sys.executable,'-m','src.db_runner','--reprocess'],check=True)
            for name,(_,expected) in cases.items():
                result=conn.execute('SELECT code FROM public.nlp_current_description_findings WHERE ticket_id=%s',(ids[name],)).fetchall()
                assert {r['code'] for r in result}==expected,(name,result)
                version=conn.execute('SELECT pipeline_version FROM public.nlp_ticket_text WHERE ticket_id=%s',(ids[name],)).fetchone()
                assert version['pipeline_version']==RULE_PIPELINE_VERSION
            assert not conn.execute('SELECT 1 FROM public.nlp_review_queue WHERE ticket_id=ANY(%s)',(list(ids.values()),)).fetchone()
            initial=dashboard();assert initial['review-queue']==[]
            assert any(r['code']=='WeightMeasures' for r in initial['recommendations'])
            assert any(r['section_id']==section and r['prominent_code']=='WeightMeasures' for r in initial['section-insights'])
            conn.execute("UPDATE public.tickets SET description='No violations found.',updated_at=clock_timestamp() WHERE id=%s",(ids['short_mass'],))
            conn.execute("UPDATE public.tickets SET status='Void',updated_at=clock_timestamp() WHERE id=%s",(ids['scale_seal'],))
            assert not conn.execute('SELECT 1 FROM public.nlp_current_description_findings WHERE ticket_id=ANY(%s)',([ids['short_mass'],ids['scale_seal']],)).fetchone()
            dashboard()
            report={'version':RULE_PIPELINE_VERSION,'fixtures':len(cases),'worker_and_database_findings':'passed',
                    'http_routes':['recommendations','section-insights','review-queue'],
                    'automatic_actions_without_user_queue':True,'edited_and_voided_findings_invalidated_immediately':True,
                    'scope':'Isolated portable development database only; no production deployment.'}
            output=Path('evaluation/candidate34/db_verification.json');output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(report,indent=2))
        finally:
            if ids:conn.execute('DELETE FROM public.tickets WHERE id=ANY(%s)',(list(ids.values()),))
            rebuild_insights(conn,catalog()[0])


if __name__=='__main__':main()
