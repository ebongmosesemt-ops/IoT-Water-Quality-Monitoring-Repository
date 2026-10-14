#!/usr/bin/env python3
"""Reproducible analysis for the Owo River IoT water-quality dataset.

This script is designed to run from any machine without hard-coded absolute paths.
It reproduces the principal analyses reported for the study while making the
quality-control and WQI definitions explicit.

The Node-RED flow in this repository is a reconstructed reference flow based on
the documented architecture and firmware. It is not claimed to be the original
exported production flow.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.metrics import confusion_matrix, cohen_kappa_score, mean_absolute_error, mean_squared_error, r2_score, precision_score, recall_score, f1_score
from sklearn.preprocessing import StandardScaler

RAW_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "owo_river_08Jun_23Aug_2026_adafruit_1.csv"
CLEAN_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "owo_river_08Jun_23Aug_2026_CLEANED_QC_v2.csv"
LAB_DEFAULT = Path(__file__).resolve().parents[1] / "data" / "laboratory_reference_values.csv"
OUT_DEFAULT = Path(__file__).resolve().parents[1] / "results"

RAW_FEATURES = ['value_ph','value_temperature_c','value_turbidity_ntu','value_ec_uscm','value_tds_mgl','value_do_mgl']
CLEAN_FEATURES = ['pH_clean','temperature_clean','turbidity_clean','ec_clean','tds_clean','do_clean']
LABELS = ['pH','temperature','turbidity','ec','tds','do']

# Historical QC evidence in the released dataset shows these operational bounds.
# They are separated from the statistical analysis so they can be changed without
# altering the rest of the workflow.
QC_RANGES = {
    'value_ph': (0.0, 14.0),
    'value_temperature_c': (0.0, 50.0),
    'value_turbidity_ntu': (0.0, 3000.0),
    'value_ec_uscm': (0.0, 5000.0),
    'value_tds_mgl': (0.0, 5000.0),
    'value_do_mgl': (0.0, 20.0),
}

# NOTE: these audit limits are NOT the deployed limits. The deployed validation log records 1.5 (pH),
# 3 (DO, mg/L) and 500 (turbidity, NTU) per hour. Temperature, EC and TDS limits are not recoverable from the log.
# The supplied analysis document used these rate limits. They are retained here
# as an explicit analysis/audit configuration, not silently mixed with the
# historical flag-generation rules.
ANALYSIS_ROC = {
    'value_ph': 0.5,
    'value_temperature_c': 2.0,
    'value_turbidity_ntu': 50.0,
    'value_ec_uscm': 150.0,
    'value_tds_mgl': 75.0,
    'value_do_mgl': 3.0,
}


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--raw', type=Path, default=RAW_DEFAULT)
    p.add_argument('--cleaned', type=Path, default=CLEAN_DEFAULT)
    p.add_argument('--lab', type=Path, default=LAB_DEFAULT)
    p.add_argument('--out', type=Path, default=OUT_DEFAULT)
    return p.parse_args()


def require_columns(df, cols, name):
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{name} is missing required columns: {missing}")


def load_csv(path):
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'], utc=True, errors='coerce')
    return df.sort_values('created_at').reset_index(drop=True)


def chronology(clean):
    t0, t1 = clean['created_at'].min(), clean['created_at'].max()
    expected = int((t1 - t0).total_seconds() / 3600) + 1
    actual = len(clean)
    return {'start_utc': t0.isoformat(), 'end_utc': t1.isoformat(), 'expected_hourly_records': expected,
            'received_records': actual, 'completeness_percent': 100*actual/expected}


def qc_audit(raw, out):
    rows=[]
    for col,(lo,hi) in QC_RANGES.items():
        x=pd.to_numeric(raw[col], errors='coerce')
        n=int(((x<lo)|(x>hi)).sum())
        rows.append({'parameter':col,'rule':'range','lower':lo,'upper':hi,'violations':n,'percent':100*n/len(raw)})
    for col,limit in ANALYSIS_ROC.items():
        x=pd.to_numeric(raw[col], errors='coerce')
        n=int(x.diff().abs().gt(limit).sum())
        rows.append({'parameter':col,'rule':'rate_of_change_audit','lower':None,'upper':limit,'violations':n,'percent':100*n/len(raw)})
    tds=pd.to_numeric(raw['value_tds_mgl'],errors='coerce'); ec=pd.to_numeric(raw['value_ec_uscm'],errors='coerce')
    rows.append({'parameter':'TDS_vs_EC','rule':'tds_gt_ec','lower':None,'upper':None,'violations':int((tds>ec).sum()),'percent':100*int((tds>ec).sum())/len(raw)})
    rows.append({'parameter':'EC_vs_TDS','rule':'zero_ec_positive_tds','lower':None,'upper':None,'violations':int(((ec==0)&(tds>0)).sum()),'percent':100*int(((ec==0)&(tds>0)).sum())/len(raw)})
    pd.DataFrame(rows).to_csv(out/'qc_audit.csv',index=False)


def descriptive(clean, out):
    valid=clean[clean['row_qc'].eq('VALID')].copy()
    records=[]
    for lab,col in zip(LABELS,CLEAN_FEATURES):
        x=pd.to_numeric(valid[col],errors='coerce').dropna()
        records.append({'parameter':lab,'n':len(x),'mean':x.mean(),'sd':x.std(),'median':x.median(),
                        'min':x.min(),'max':x.max(),'skew':x.skew()})
    pd.DataFrame(records).to_csv(out/'descriptive_statistics_valid.csv',index=False)


def temporal_tests(clean,out):
    valid=clean[clean['row_qc'].eq('VALID')].copy()
    valid['month']=valid.created_at.dt.month
    rows=[]; post=[]
    for lab,col in zip(LABELS,CLEAN_FEATURES):
        groups=[valid.loc[valid.month==m,col].dropna() for m in [6,7,8]]
        if any(len(g)==0 for g in groups): continue
        h,p=stats.kruskal(*groups)
        rows.append({'parameter':lab,'H':h,'p_value':p,'significant':p<0.05})
        if p<0.05:
            for a,b,ga,gb in [('June','July',groups[0],groups[1]),('June','August',groups[0],groups[2]),('July','August',groups[1],groups[2])]:
                u,pair=stats.mannwhitneyu(ga,gb,alternative='two-sided')
                post.append({'parameter':lab,'comparison':f'{a} vs {b}','p_uncorrected':pair,'p_bonferroni':min(pair*3,1.0)})
    pd.DataFrame(rows).to_csv(out/'kruskal_wallis.csv',index=False)
    pd.DataFrame(post).to_csv(out/'posthoc_mannwhitney_bonferroni.csv',index=False)


def correlations(clean,out):
    valid=clean[clean['row_qc'].eq('VALID')][CLEAN_FEATURES]
    valid.corr('pearson').to_csv(out/'pearson_correlation.csv')
    valid.corr('spearman').to_csv(out/'spearman_correlation.csv')


def isolation_forest(clean,out):
    F=CLEAN_FEATURES
    d=clean.dropna(subset=F).copy()
    d['composite']=(d['environmental_event'].astype(bool) | d['imperfection_type'].notna()).astype(int)
    d['event']=d['environmental_event'].astype(bool).astype(int)
    d['artefact']=d['imperfection_type'].notna().astype(int)
    t0=d.created_at.min(); cut=t0+pd.Timedelta(days=14)
    test=d[d.created_at>cut].copy()
    # Primary configuration (reproduces the manuscript tables): the initial model is fitted on all
    # complete cleaned records in the first 14 days; later models use all complete records that
    # precede the month. Records flagged by the rules or by the forest are not removed from training.
    # A sensitivity run restricted to validation_flag == 0 is written to a second file.
    def fit_predict(tr, te):
        scaler=StandardScaler().fit(tr[F])
        model=IsolationForest(n_estimators=100, contamination=0.05, random_state=42)
        model.fit(scaler.transform(tr[F]))
        return (model.predict(scaler.transform(te[F]))==-1).astype(int)
    def run(only_flag0):
        keep=(lambda z: z[z.validation_flag==0]) if only_flag0 else (lambda z: z)
        train=keep(d[d.created_at<=cut])
        if len(train)<10 or len(test)==0:
            return None,None
        static=fit_predict(train,test)
        retrained=np.zeros(len(test),dtype=int)
        for m in [6,7,8]:
            hist=train if m==6 else keep(d[d.created_at<pd.Timestamp(2026,m,1,tz='UTC')])
            sel=test.created_at.dt.month.eq(m)
            if sel.any() and len(hist)>=10:
                retrained[sel.to_numpy()]=fit_predict(hist,test.loc[sel])
        return static,retrained
    def table(static,retrained):
        rows=[]
        for name,pred in [('Static',static),('Monthly_retrained',retrained)]:
            for target in ['composite','event','artefact']:
                y=test[target].to_numpy(); tn,fp,fn,tp=confusion_matrix(y,pred,labels=[0,1]).ravel()
                rows.append({'model':name,'target':target,'TN':tn,'FP':fp,'FN':fn,'TP':tp,'precision':precision_score(y,pred,zero_division=0),'recall':recall_score(y,pred,zero_division=0),'F1':f1_score(y,pred,zero_division=0),'kappa':cohen_kappa_score(y,pred),'flag_rate':pred.mean()})
        return pd.DataFrame(rows)
    st,rt=run(False)
    if st is not None:
        table(st,rt).to_csv(out/'isolation_forest_performance.csv',index=False)
    st0,rt0=run(True)
    if st0 is not None:
        table(st0,rt0).to_csv(out/'isolation_forest_performance_flag0_training_sensitivity.csv',index=False)


def lab_validation(clean, lab, out):
    if lab is None or not lab.exists(): return
    ref=pd.read_csv(lab)
    ref['date']=pd.to_datetime(ref['date'],utc=True)
    sensor_cols={'pH':'pH_sensor','temperature':'temperature_sensor','tds':'tds_sensor','ec':'ec_sensor','do':'do_sensor','turbidity':'turbidity_sensor'}
    rows=[]
    for _,r in ref.iterrows():
        rows.append(r.to_dict())
    ref.to_csv(out/'laboratory_reference_values_copy.csv',index=False)
    metrics=[]
    for param,scol in sensor_cols.items():
        a=ref[scol].astype(float); b=ref[f'{param}_lab'].astype(float)
        metrics.append({'parameter':param,'n':len(a),'MAE':mean_absolute_error(b,a),'RMSE':mean_squared_error(b,a)**0.5,
                        'bias_sensor_minus_lab':(a-b).mean(),'R2':r2_score(b,a)})
    pd.DataFrame(metrics).to_csv(out/'laboratory_validation_metrics.csv',index=False)


def wqi(clean,out):
    # Final dissertation implementation: Brown weighted arithmetic method,
    # five parameters, inverse permissible standards, DO inverted rating.
    specs={
        'pH_clean':{'ideal':7.0,'standard':8.5,'weight':1/8.5},
        'do_clean':{'ideal':14.6,'standard':5.0,'weight':1/5.0},
        'turbidity_clean':{'ideal':0.0,'standard':5.0,'weight':1/5.0},
        'tds_clean':{'ideal':0.0,'standard':500.0,'weight':1/500.0},
        'ec_clean':{'ideal':0.0,'standard':1000.0,'weight':1/1000.0},
    }
    total=sum(x['weight'] for x in specs.values())
    for x in specs.values(): x['Wi']=x['weight']/total
    def one(r):
        vals=[]; ws=[]
        for col,s in specs.items():
            v=r[col]
            if pd.isna(v): continue
            if col=='do_clean': q=100*(s['ideal']-v)/(s['ideal']-s['standard'])
            else: q=100*(v-s['ideal'])/(s['standard']-s['ideal'])
            q=max(0.0,q)
            vals.append(q*s['Wi']); ws.append(s['Wi'])
        if len(vals)<4: return np.nan
        return sum(vals)/sum(ws)
    valid=clean[clean['row_qc'].eq('VALID')].copy()
    valid['WQI']=valid.apply(one,axis=1)
    def cls(x):
        if pd.isna(x): return 'Insufficient Data'
        if x<=25:return 'Excellent'
        if x<=50:return 'Good'
        if x<=75:return 'Poor'
        if x<=100:return 'Very Poor'
        return 'Unfit'
    valid['WQI_Class']=valid.WQI.map(cls)
    valid[['created_at','WQI','WQI_Class']].to_csv(out/'wqi_valid_records.csv',index=False)
    summary=valid.groupby(valid.created_at.dt.month).WQI.agg(['count','mean','median','min','max']).reset_index().rename(columns={'created_at':'month'})
    summary['month']=summary['month'].map({6:'June',7:'July',8:'August'})
    summary.to_csv(out/'wqi_monthly_summary.csv',index=False)
    valid.WQI_Class.value_counts().rename_axis('class').reset_index(name='records').to_csv(out/'wqi_class_distribution.csv',index=False)
    return valid


def main():
    args=parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    raw=load_csv(args.raw); clean=load_csv(args.cleaned)
    require_columns(raw,['created_at']+RAW_FEATURES,'Raw dataset')
    require_columns(clean,['created_at']+CLEAN_FEATURES+['validation_flag','row_qc','environmental_event','imperfection_type'],'Cleaned dataset')
    (args.out/'dataset_profile.json').write_text(json.dumps({'raw_shape':raw.shape,'cleaned_shape':clean.shape,'chronology':chronology(clean),'row_qc_counts':clean.row_qc.value_counts(dropna=False).to_dict()},indent=2,default=str))
    qc_audit(raw,args.out); descriptive(clean,args.out); temporal_tests(clean,args.out); correlations(clean,args.out); isolation_forest(clean,args.out); lab_validation(clean,args.lab,args.out); wqi(clean,args.out)
    print(f"Analysis complete. Results written to {args.out}")

if __name__=='__main__': main()
