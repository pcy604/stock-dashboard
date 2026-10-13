import pandas as pd, numpy as np, sys, os, FinanceDataReader as fdr
import ksim
wc=pd.read_parquet('kr_wc.parquet'); wm=pd.read_parquet('kr_wm.parquet')
SP=pd.read_parquet('sig_price.parquet'); SE=pd.read_parquet('sig_earn.parquet')
k=fdr.DataReader('KS11','2013-01-01').Close; kw=k.resample('W-FRI').last().reindex(wc.index).ffill()
START=sys.argv[1] if len(sys.argv)>1 else '2014-01-01'
px=wc[wc.index>=START]; kos=kw[kw.index>=START]
last_row=np.array([ (np.where(px[c].notna())[0].max() if px[c].notna().any() else -1) for c in px.columns])
cr=pd.Series((1.025)**(1/52)-1,index=px.index)
kr_ret=kos.pct_change().fillna(0)
mc=wm.reindex(index=px.index,columns=px.columns).values
def go(name,sig,n=8,order='random',idle_kospi=False,**kw):
    g=sig[sig.index>=START].reindex(columns=px.columns).fillna(False)
    R=[];C=[]
    for sd in range(1 if order!='random' else n):
        h,x=ksim.run(px,g,slots=20,delay=1,order=order,mc=mc,seed=100+sd,cash_r=(kr_ret if idle_kospi else cr),last_row=last_row,**kw)
        R.append(ksim.stats(h.v,kos)[0]); C.append(h.v)
    D=pd.DataFrame(R); med=pd.concat(C,axis=1).median(axis=1)
    hp=[]
    for a,b in [(START[:4],'2019'),('2020','2026')]:
        s_=med[a:b]; hp.append(f"{((s_.iloc[-1]/s_.iloc[0])**(52/len(s_))-1)*100:5.1f}")
    print(f"{name:34s} CAGR {D.CAGR.median():5.1f} [{D.CAGR.quantile(.1):5.1f}~{D.CAGR.quantile(.9):5.1f}] MDD {D.MDD.median():6.1f} Sh {D.Sharpe.median():.2f} 최악해 {D.worst_yr.median():6.1f} 이긴해 {D.beat_yrs.iloc[0] if order!='random' else D.beat_yrs.str.split('/').str[0].astype(int).median()} | 전/후반 {hp}",flush=True)
    return med
b=ksim.stats(kos,kos)[0]; print(f"{'KOSPI 매수보유 ('+START[:4]+'~)':34s} CAGR {b['CAGR']:5.1f} MDD {b['MDD']:6.1f} Sh {b['Sharpe']:.2f} 최악해 {b['worst_yr']}")
which=sys.argv[2] if len(sys.argv)>2 else 'A'
if which=='A':
    go('가격신호 · 고점-30 (현행 KR-P1)',SP,stop=30)
    go('가격신호 · 고점-20',SP,stop=20)
    go('가격신호 · ★손절없음+익절52/33+트림',SP,stop=None,take=(52,33),trim=15,cap=10)
if which=='B':
    go('가격신호 · ★ + 빈칸 KOSPI',SP,stop=None,take=(52,33),trim=15,cap=10,idle_kospi=True)
    go('가격신호 · ★ 시총 작은 순',SP,order='mc_asc',stop=None,take=(52,33),trim=15,cap=10)
    go('가격신호 · 고점-30 시총 작은 순',SP,order='mc_asc',stop=30)
if which=='C':
    go('실적신호(생존편향) · 고점-30',SE,stop=30)
    go('실적신호(생존편향) · ★',SE,stop=None,take=(52,33),trim=15,cap=10)
