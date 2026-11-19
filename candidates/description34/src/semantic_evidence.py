"""Local-only entailment experiment; not enabled without validation calibration."""
from hashlib import sha256
import json
from pathlib import Path
import re

from .breach_evidence import has, quantitative_proof
from .description_evidence import COMPLIANT_CATEGORY, supports_category
from .incidents import UNCERTAIN

HYPOTHESES = {
 'Vendor Identification':"The seller failed the assigned identification requirement.",
 'Permit & Licensing':"The vendor's required permit or certificate is invalid or missing.",
 'Sanitation':"The vendor's food handling or stall hygiene is unsanitary.",
 'Lighting & Energy':"The vendor used lighting or electricity contrary to the stated restriction.",
 'Stall Occupancy':"The stallholder's use of the stall violates the stated occupancy condition.",
 'Stall Management':"The stallholder failed to perform the stated management duty.",
 'Stall Construction':"The stallholder altered the stall without the required approval.",
 'Utilities':"The vendor used water or drainage contrary to the stated utility requirement.",
 'Stall Rental':"The stallholder failed to fulfill the stated rent or lease obligation.",
 'Illegal Vendor':"The vendor sold goods without authorization for that location.",
 'Public Order':"The vendor caused dangerous disorder that disrupted market activity.",
 'Liquor':"The vendor served or consumed alcohol contrary to the stated restriction.",
 'Market Conduct':"The vendor mistreated a customer or another vendor.",
 'Obstruction':"The vendor's items obstructed a passage.",
 'DressCode':"The worker's clothing violated the stated attire requirement.",
 'Bladed Instruments':"The worker violated the stated blade handling or storage requirement.",
 'Traffic':"The vendor's vehicle violated the stated traffic restriction.",
 'Porter Regulation':"The porter violated the stated porter operating requirement.",
 'Promotions':"The vendor's promotion violated a stated condition.",
 'Advertising':"The vendor's advertisement violated a stated content or approval condition.",
 'Signage & Streamers':"The vendor's sign violated a stated display requirement.",
 'Entertainment Activities':"The vendor's event violated a stated operating condition.",
 'Lighting Facilities':"A light failed and keeping it working was the stallholder's duty.",
 'Market Rules':"The vendor breached the specific market operating rule described.",
 'Price Monitoring':"The vendor failed to provide required accurate price information.",
 'Market Fees & Surcharges':"The vendor failed to pay the stated required market fee in full.",
 'Resisting Authority':"The vendor interfered with an inspector performing an enforcement duty.",
 'General Penalties':"The vendor continued trading while an active suspension or closure was in force.",
}
FACTS = {
 'Vendor Identification':["The seller has no valid vendor ID.","The ID belongs to another person.","The ID is not displayed as required.","The name or photograph on the ID is not legible."],
 'Permit & Licensing':["The business permit has expired.","The required certificate is missing.","The license was revoked.","The permit does not cover the vendor's activity."],
 'Sanitation':["The food is exposed to contamination.","The food preparation surface is dirty.","The vendor is mishandling waste."],
 'Lighting & Energy':["The vendor uses colored lights to make food look fresh.","The freezer uses a common outlet instead of its required metered outlet.","The vendor is charging devices in violation of a restriction."],
 'Stall Occupancy':["The vendor is using space that was not awarded to them.","A household holds more stalls than allowed.","The stall is being used for something other than selling."],
 'Stall Management':["The stallholder failed to report damage.","The required emergency contact information is missing or incorrect.","The required security or safety equipment is not maintained."],
 'Stall Construction':["The vendor built an improvement without approval.","The completed work differs from the approved plan.","The vendor has finished construction while approval is still pending."],
 'Utilities':["The vendor made an unauthorized water connection.","The vendor drew water outside the permitted hours.","The vendor damaged or obstructed drainage."],
 'Stall Rental':["The rent remains unpaid.","The rent check was dishonored.","The stall was subleased against the lease conditions."],
 'Illegal Vendor':["The vendor is selling in a location without permission.","The vendor is selling without the required vending authorization."],
 'Public Order':["The vendor caused a fight.","The vendor caused a dangerous crowd that disrupted trade.","The vendor caused a disturbance that drove shoppers away."],
 'Liquor':["The vendor served alcohol in open containers.","The vendor drank alcohol in the stall.","The vendor sold alcohol during an active liquor ban."],
 'Market Conduct':["The vendor harassed a customer.","The vendor deceived a customer.","The vendor mistreated another vendor."],
 'Obstruction':["The vendor's goods block the passage.","The vendor placed items across the exit.","People cannot pass because of the vendor's items."],
 'DressCode':["The worker did not wear the required protective clothing.","The worker's clothes are dirty or torn.","The worker is wearing prohibited attire."],
 'Bladed Instruments':["A blade was handled contrary to the stated restriction.","Knives were not locked away when not in use.","A blade was used outside the permitted area."],
 'Traffic':["The vendor's vehicle went the wrong way.","The vendor's vehicle entered a prohibited area.","The vendor's delivery breached a loading or parking restriction."],
 'Porter Regulation':["The porter lacks required identification.","The porter's load exceeds the stated limit.","The porter did not wear the required numbered vest."],
 'Promotions':["The raffle violated its approved conditions.","The promotion gave items to prohibited recipients.","The promised promotion prize was not provided."],
 'Advertising':["The advertisement disparaged another vendor.","Advertisements were distributed without required approval.","The vendor used customers' contact details without consent."],
 'Signage & Streamers':["The sign exceeds the stated size or placement limit.","The sign covers another stall's frontage or number.","The sign remained after its approved display period."],
 'Entertainment Activities':["The vendor's event exceeded its permitted attendance.","The event's sound violated the stated conditions.","The event continued past the approved time."],
 'Lighting Facilities':["The light is not working despite the stallholder's maintenance duty.","The required fixture was removed and not replaced."],
 'Market Rules':["The vendor smoked where smoking is prohibited.","The vendor traded outside the allowed hours.","The vendor violated a specified cleaning or delivery rule."],
 'Price Monitoring':["The price display omits the required unit.","The vendor charged above the displayed price for the same quantity.","Required price information is missing."],
 'Market Fees & Surcharges':["The required fee remains unpaid.","The vendor paid less than the required fee."],
 'Resisting Authority':["The vendor obstructed the inspector.","The vendor concealed their identity to interfere with enforcement.","The vendor forcibly interfered with inspection equipment."],
 'General Penalties':["The vendor continued selling during an active suspension.","The stall continued trading while a closure order remained in force."],
}
HYPOTHESES={code:[abstract,*FACTS[code]] for code,abstract in HYPOTHESES.items()}
COMPLIANCE = {
 'Vendor Identification':r'\b(?:id worn and valid|valid vendor id|vendor id.*valid)\b',
 'Permit & Licensing':r'\bbusiness permit current\b|\bhealth certificate on file\b',
 'Sanitation':r'\b(?:garbage in sealed bags|fish on ice and covered)\b',
 'Stall Occupancy':r'\boccupied by the awardee\b|\boccupant matches\b',
 'Stall Rental':r'\brent paid up to date\b|\bsettled in full\b',
 'Bladed Instruments':r'\bknives in a locked\b',
 'Market Fees & Surcharges':r'\bdaily fee paid\b|\bfee receipt shows full payment\b',
}


def eligible(code, unit):
    """Conservative prefilter for an offline semantic-verifier experiment."""
    text=unit.text
    if (code not in HYPOTHESES or unit.blocked or unit.is_requirement or '?' in unit.context
            or UNCERTAIN.search(unit.context) or not supports_category(code,unit.context)):
        return False
    if code in COMPLIANCE and has(COMPLIANCE[code],text):
        return False
    if code in COMPLIANT_CATEGORY and COMPLIANT_CATEGORY[code].search(text):
        return False
    if quantitative_proof(code,unit) is False:
        return False
    if code=='Permit & Licensing' and has(r'construction|counter extension|sidewalk permit|vending permit|scale|event approval|promotion approval',text):
        return False
    if code=='Illegal Vendor' and not has(r'\b(?:selling|nagtitinda|nagbebenta|hawker|peddler)\b',text):
        return False
    if code=='Vendor Identification' and has(r'porter|kargador|mobile vendor id|inspector|citation',text):
        return False
    if code=='Stall Occupancy' and has(r'\bdwelling\b',text):
        return False
    if code=='Stall Management' and has(r'extinguisher',text) and not has(r'duty|contract|requires|must|required',unit.context):
        return False
    if code=='Lighting Facilities' and not has(r'duty|contract|agreement|kontrata|kasunduan|must|kailangang|dapat|responsib',unit.context):
        return False
    if code=='Market Rules' and not has(r'smoking|smoked|naninigarilyo|closing|cleaning|service gate|delivery gate|oras ng|araw ng|aso|children|dwelling',text):
        return False
    if code=='Liquor' and has(r'\bno (?:one|person)\b.{0,30}(?:drinking|selling|serving)|\bsmell of alcohol\b',text):
        return False
    if code=='Resisting Authority' and has(r'(?:paid|binayad|binayaran).{0,100}(?:posing|nagpanggap)',text):
        return False
    if code=='Advertising' and has(r'phone|numbers|numero|receipts|ad texts|ad messages',text) and not has(r'without consent|no consent|walang pahintulot|without permission',text):
        return False
    if code=='Bladed Instruments' and has(r'utensil|kitchenware',text):
        return False
    return True


class SemanticEvidence:
    def __init__(self,path):
        import onnxruntime as ort
        from transformers import AutoTokenizer
        self.path=Path(path)
        provenance=json.loads((self.path/'provenance.json').read_text(encoding='utf-8'))
        for name,item in provenance['files'].items():
            if sha256((self.path/name).read_bytes()).hexdigest()!=item['sha256']:
                raise ValueError('Semantic verifier identity changed: '+name)
        self.provenance=provenance
        options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(self.path/'onnx/model_quantized.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.tokenizer=AutoTokenizer.from_pretrained(str(self.path),local_files_only=True,use_fast=True,trust_remote_code=False)

    def score_many(self,pairs):
        import numpy as np
        expanded=[(i,text,hypothesis) for i,(code,text) in enumerate(pairs) for hypothesis in HYPOTHESES[code]]
        probabilities=np.zeros(len(pairs))
        for start in range(0,len(expanded),16):
            group=expanded[start:start+16]
            values=self.tokenizer([text for i,text,h in group],[h for i,text,h in group],padding=True,truncation=False,return_tensors='np')
            if values['input_ids'].shape[1]>512:
                # Never drop a trailing qualifier to make a case fit the model.
                output=[]
                for i,text,h in group:
                    one=self.tokenizer(text,h,return_tensors='np',truncation=False)
                    output.append(0.0 if one['input_ids'].shape[1]>512 else float(self._score(one)[0]))
            else:
                output=self._score(values).tolist()
            for (index,_,_),score in zip(group,output):
                probabilities[index]=max(probabilities[index],score)
        return probabilities

    def _score(self,values):
        import numpy as np
        logits=self.session.run(None,{x.name:values[x.name].astype(np.int64) for x in self.session.get_inputs()})[0]
        softmax=np.exp(logits-logits.max(axis=1,keepdims=True));softmax/=softmax.sum(axis=1,keepdims=True)
        return softmax[:,0]
