# 실행 위치: marcap-20XX.parquet 를 받아 둔 폴더 (https://raw.githubusercontent.com/FinanceData/marcap/master/data/)
import pandas as pd, numpy as np, glob, time
t=time.time()
cols=['Code','Date','Close','High','Amount','Marcap','MarketId','Name']
parts=[]
for f in sorted(glob.glob('marcap-20*.parquet')):
    x=pd.read_parquet(f,columns=cols); x=x[x.MarketId.isin(['STK','KSQ'])]; parts.append(x)
d=pd.concat(parts); d['Date']=pd.to_datetime(d.Date); d['Code']=d.Code.astype(str).str.zfill(6)
d=d[d.Close>0].drop_duplicates(['Code','Date'],keep='last')
print('rows',len(d),'codes',d.Code.nunique(), d.Date.min().date(), d.Date.max().date(), round(time.time()-t))
C=d.pivot(index='Date',columns='Code',values='Close').astype('float32')
A=d.pivot(index='Date',columns='Code',values='Amount').astype('float32')
M=d.pivot(index='Date',columns='Code',values='Marcap').astype('float32')
names=d.groupby('Code').Name.last()
last_date=d.groupby('Code').Date.max()
print('pivot',C.shape, round(time.time()-t))
# 일간 52주 신고가 돌파 (종가 기준, 직전 252거래일 최고 종가 초과)
hi=C.rolling(252,min_periods=200).max().shift(1)
brk=(C>hi)&(C>=1000)
adv=A.rolling(20,min_periods=15).mean()
# 주간 집계 (금요일 종가 기준, 라벨=그 주 금요일)
W=lambda df,f: getattr(df.resample('W-FRI'),f)()
wc=W(C,'last'); wm=W(M,'last'); wadv=W(adv,'last'); wb=W(brk.astype('float32'),'max')>0
# 상장폐지: 마지막 거래일 이후 NaN — 마지막 주 이후 가격 없음
wc.to_parquet('kr_wc.parquet'); wm.to_parquet('kr_wm.parquet'); wadv.to_parquet('kr_wadv.parquet'); wb.astype('int8').to_parquet('kr_wb.parquet')
pd.DataFrame({'name':names,'last':last_date}).to_parquet('kr_meta.parquet')
print('weekly',wc.shape,'delisted(마지막거래 2026-09 이전)',(last_date<'2026-09-01').sum(), round(time.time()-t))
