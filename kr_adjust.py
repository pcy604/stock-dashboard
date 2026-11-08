# -*- coding: utf-8 -*-
"""한국 수정주가 (2026-11-08) — FinanceData/marcap 일별 원가격(비수정)을 수정주가로.

왜: marcap Close 는 그날의 원래 가격이다. 액면분할·병합·무상증자·감자가 가짜 급등락이 된다.
  · 옛 보정(quant_panel 2026-10-31)은 '같은 날 주식수가 1.5배 넘게 바뀌고 가격이 반대로' 일 때만 잡았다.
    → **무상증자처럼 주식수 반영이 며칠 늦는 경우를 놓쳤다**(메가스터디 2018-06-18 원가격 −68.5%, 주식수 그대로,
      KRX 등락률은 −6.48%) — 퀀트 백테스트가 이걸 '래칫 손절 −64.7%'로 기록하고 있었다(차니 "믿을 수 있는 거 맞지?").
  · winners_reverse 의 보정은 주식수 기준이라 같은 구멍.
방법(하루 단위, 종목마다):
  ① KRX 등락률(ChangesRatio)은 기준가(권리락·분할 반영) 대비라 그 자체가 수정 수익률이다.
     원가격 수익률과 0.1(로그) 넘게 어긋나고, 직전 거래일이 4일 이내(거래정지·자료 공백이 아님)이고,
     |등락률| ≤ 30.5%(가격제한폭 안 = 정상 거래일)면 그날 수익률을 등락률로 바꾼다.
  ② 아니면, 주식수가 1.5배 넘게 바뀌고 가격이 반대 방향으로 그 70% 이상 움직인 날(감자 정리매매 등)은
     원가격비 × 주식수비(= 시총비)를 그날 수익률로.
  ③ 나머지는 원가격 그대로.
결과는 '그날 이후 비율의 곱'으로 과거 가격을 나누는 계수 F — 최신 가격은 원가격과 같다(화면 현재가와 일치).
"""
import numpy as np
import pandas as pd


def factor(d: pd.DataFrame) -> pd.Series:
    """d: Code·Date·Close (+ ChangesRatio · Stocks 있으면 사용), Code·Date 순 정렬. 반환: 원가격 ÷ F = 수정주가 인 F(d 와 같은 인덱스)."""
    g = d.groupby("Code", sort=False)
    pc = g.Close.shift(1)
    lr = np.log(d.Close / pc)
    step = pd.Series(0.0, index=d.index)                      # 로그 조정량 = lr − 수정수익률 (분할이면 ln(1/2) 등)
    gap = (d.Date - g.Date.shift(1)).dt.days
    used = pd.Series(False, index=d.index)
    if "ChangesRatio" in d.columns:
        cr = pd.to_numeric(d.ChangesRatio, errors="coerce")
        lc = np.log1p(cr / 100)
        m1 = ((lr - lc).abs() > 0.1) & (gap <= 4) & (cr.abs() <= 30.5) & lc.notna()
        step = step.where(~m1, lr - lc)
        used |= m1
    if "Stocks" in d.columns:
        ls = np.log(d.Stocks / g.Stocks.shift(1))
        m2 = ~used & (ls.abs() > np.log(1.5)) & (np.sign(lr) == -np.sign(ls)) & (lr.abs() >= 0.7 * ls.abs())
        step = step.where(~m2, -ls)                             # 수정수익률 = lr + ls → 조정량 = −ls
    step = step.fillna(0.0)
    # 그날 '이전' 가격에 적용: 수정주가_t = 원가격_t × exp(Σ_{s>t} step_s) → F_t = exp(−Σ_{s>t} step_s)
    return np.exp(-step.groupby(d.Code, sort=False).transform(lambda s: s[::-1].cumsum()[::-1].shift(-1).fillna(0.0)))


def events(d: pd.DataFrame) -> int:
    f = factor(d)
    return int((f.groupby(d.Code).diff().abs() > 1e-9).sum())
