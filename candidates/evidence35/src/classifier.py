"""Optional local multi-label classifier trained on a sufficiently sized gold dataset."""
from pathlib import Path
from .engine import normalize

class TrainedClassifier:
    def __init__(self, trusted_local_file):
        import joblib
        path=Path(trusted_local_file).resolve()
        if not path.is_file():raise FileNotFoundError(path)
        # joblib uses pickle; load ONLY locally trained artifacts, never user-submitted files.
        self.bundle=joblib.load(path)

    def predict(self,clean_text,threshold=0.78):
        X=self.bundle['vectorizer'].transform([normalize(clean_text)])
        model=self.bundle['model']
        output=[]
        for i,(code,estimator) in enumerate(zip(self.bundle['codes'],model.estimators_)):
            if len(estimator.classes_)!=2:continue
            proba=estimator.predict_proba(X)[0,1]
            if proba>=threshold:output.append({'code':code,'confidence':round(float(proba),3)})
        return output
