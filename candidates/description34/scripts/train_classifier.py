"""Optional Stage 2 training on human-confirmed data only.

Use a real validated dataset with >=300 reviewed descriptions; short demo CSV is blocked.
Group-holdout by vendor prevents obvious near-duplicate leakage.
"""
from pathlib import Path
import csv,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.engine import normalize,catalog

def train(raw_csv,gold_csv,out_path):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.preprocessing import MultiLabelBinarizer
    from sklearn.metrics import f1_score
    import numpy as np,joblib
    taxonomy,_=catalog()
    with open(raw_csv,encoding='utf-8-sig',newline='') as f:r={x['ticket_id']:x for x in csv.DictReader(f)}
    with open(gold_csv,encoding='utf-8-sig',newline='') as f:g={x['ticket_id']:x for x in csv.DictReader(f)}
    pairs=[]
    for tid,x in r.items():
        if tid not in g or g[tid].get('annotation_status') not in ('labeled','clear'):continue
        codes=sorted(set(filter(None,g[tid].get('gold_codes','').split('|'))))
        if not set(codes).issubset(taxonomy):raise ValueError(f'Unknown labels in {tid}')
        pairs.append((normalize(x['description']),codes,x.get('vendor_id') or tid))
    if len(pairs)<300:raise ValueError(f'Only {len(pairs)} confirmed rows; collect >=300 REAL labeled examples first.')
    Xtxt=[x[0] for x in pairs]; labels=[x[1] for x in pairs];groups=[x[2] for x in pairs]
    mlb=MultiLabelBinarizer(classes=sorted(taxonomy));Y=mlb.fit_transform(labels)
    if any(Y.sum(axis=0)<10):raise ValueError('Collect at least 10 confirmed positives per code before this starter trainer.')
    split=GroupShuffleSplit(n_splits=1,test_size=0.2,random_state=42)
    train_idx,test_idx=next(split.split(Xtxt,Y,groups))
    if len(test_idx)<30:raise ValueError('Held-out group too small; collect more vendors.')
    vec=TfidfVectorizer(analyzer='char',ngram_range=(2,5),min_df=2,sublinear_tf=True,max_features=100000)
    Xtrain=vec.fit_transform([Xtxt[i] for i in train_idx]); Xtest=vec.transform([Xtxt[i] for i in test_idx])
    model=OneVsRestClassifier(LogisticRegression(max_iter=2000,class_weight='balanced'))
    model.fit(Xtrain,Y[train_idx])
    prob=model.predict_proba(Xtest)
    pred=(prob>=0.78).astype(int)
    print('Held-out vendor-group micro F1:',round(f1_score(Y[test_idx],pred,average='micro',zero_division=0),3))
    print('Held-out vendor-group macro F1:',round(f1_score(Y[test_idx],pred,average='macro',zero_division=0),3))
    print('Precision/recall thresholds need tuning on separate validation set; no auto-release.')
    out=Path(out_path);out.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump({'vectorizer':vec,'model':model,'codes':list(mlb.classes_)},out)
    print('Saved trained model to',out)
if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('Usage: python scripts/train_classifier.py RAW.csv GOLD.csv models/violation_classifier.joblib')
    train(*sys.argv[1:])
