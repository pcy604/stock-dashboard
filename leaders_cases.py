# -*- coding: utf-8 -*-
"""
주도주 사례 — 규칙⑥이 실제로 언제 매수 신호를 냈는가

25종 카드덱(2026-08-02)은 표본 25종만 보고 만든 것이라, 거기서 나온 결론
(신고가 -15% 이내 진입 · PSR 2.4배)은 이후 유니버스 1,271종 검증에서 기각됐다.
이 스크립트는 그 사례들 위에 '확정 규칙⑥의 실제 신호'를 얹는다.

  진입: RS13>1.5 AND (흑자전환 OR 이익폭증) AND OPM>0  → 그 주 금요일 종가
  청산: 진입 후 주봉 종가 고점 대비 -20%
  재진입: 청산 후 다시 신호가 뜨면 허용

출력: results/cases/{sym}.png  +  results/cases/trades.json
실행: python leaders_cases.py
"""
import os, json, base64, io as _io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import leaders_boost as B

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "cases")
TRAIL = 0.20

CASES = [
    ("TSLA", "테슬라",       "19-20"), ("NVDA", "엔비디아",   "23-24"),
    ("PLTR", "팔란티어",     "24-25"), ("BE",   "블룸에너지", "25-26"),
    ("SMCI", "슈퍼마이크로", "23-24"), ("VST",  "비스트라",   "23-24"),
    ("APP",  "앱러빈",       "24-25"), ("MU",   "마이크론",   "25-26"),
    ("AVGO", "브로드컴",     "23-24"), ("ENPH", "엔페이즈",   "20-21"),
    ("CEG",  "콘스텔레이션", "23-24"), ("AMD",  "AMD",        "18-21"),
    ("MRNA", "모더나",       "20-21"),
]

# 색 — 보고서와 같은 계열
INK, ACC, POS, NEG, MUT, GRID = "#12161b", "#17415c", "#1f6b45", "#a03028", "#6d7883", "#dde3ea"


def signals(df):
    """규칙⑥ 충족 주차 불리언 시리즈."""
    return ((df.rs_13w > 1.5) & (df.opm > 0) &
            ((df.op_turn == 1) | (df.b_any == 1)) &
            (df.adv_20d >= 5e6) & (df.marcap >= 2e9)).fillna(False)


def simulate(df):
    """신호 → 진입, 고점 대비 -20% → 청산. 청산 뒤 재신호 시 재진입."""
    sig = signals(df).values
    px = df.close.values
    dt = df.as_of.values
    trades, i, n = [], 0, len(df)
    while i < n:
        if not sig[i] or not np.isfinite(px[i]):
            i += 1; continue
        entry_i, peak = i, px[i]
        j = i + 1
        while j < n:
            if np.isfinite(px[j]):
                peak = max(peak, px[j])
                if px[j] <= peak * (1 - TRAIL):
                    break
            j += 1
        exit_i = min(j, n - 1)
        closed = j < n
        trades.append(dict(
            entry_date=str(pd.Timestamp(dt[entry_i]).date()), entry_px=round(float(px[entry_i]), 2),
            exit_date=str(pd.Timestamp(dt[exit_i]).date()) if closed else None,
            exit_px=round(float(px[exit_i]), 2) if closed else None,
            peak_px=round(float(peak), 2),
            ret=round((px[exit_i] / px[entry_i] - 1) * 100, 1),
            hold_wk=int(exit_i - entry_i), status="closed" if closed else "open",
            entry_i=entry_i, exit_i=exit_i))
        i = exit_i + 1
    return trades


def chart(sym, name, era, df, trades):
    d = df.reset_index(drop=True)
    x = pd.to_datetime(d.as_of)
    y = d.close.astype(float)

    fig, ax = plt.subplots(figsize=(10.4, 3.5), dpi=110)
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")

    ax.plot(x, y, color=INK, lw=1.15, zorder=3)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(True, which="major", color=GRID, lw=.7, zorder=0)
    ax.grid(True, which="minor", color=GRID, lw=.35, alpha=.6, zorder=0)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(GRID)
    ax.tick_params(labelsize=8, colors=MUT, length=3)

    for t in trades:
        a, b = t["entry_i"], t["exit_i"]
        good = t["ret"] >= 0
        ax.axvspan(x[a], x[b], color=(POS if good else NEG), alpha=.075, zorder=1)
        ax.plot([x[a]], [y[a]], marker="^", ms=8, color=ACC,
                markeredgecolor="white", markeredgewidth=.8, zorder=5)
        if t["status"] == "closed":
            ax.plot([x[b]], [y[b]], marker="v", ms=8, color=(POS if good else NEG),
                    markeredgecolor="white", markeredgewidth=.8, zorder=5)
        ax.annotate(f"{t['ret']:+.0f}%", (x[a], y[a]), textcoords="offset points",
                    xytext=(0, -15), ha="center", fontsize=8.5, fontweight="bold",
                    color=(POS if good else NEG), zorder=6)

    ax.set_title(f"{sym} · {name} {era}   —   ▲ 규칙⑥ 진입 / ▼ 고점 −20% 청산",
                 fontsize=10, color=INK, loc="left", pad=8)
    fig.tight_layout(pad=.6)
    buf = _io.BytesIO(); fig.savefig(buf, format="png", facecolor="white"); plt.close(fig)
    png = buf.getvalue()
    with open(os.path.join(OUT, f"{sym}.png"), "wb") as f:
        f.write(png)
    return base64.b64encode(png).decode()


def main():
    os.makedirs(OUT, exist_ok=True)
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    out = {}
    for sym, name, era in CASES:
        sub = d[d.sym == sym].sort_values("as_of")
        if sub.empty:
            print(f"  {sym:6s} 데이터 없음"); continue
        tr = simulate(sub)
        b64 = chart(sym, name, era, sub, tr)
        for t in tr: t.pop("entry_i"); t.pop("exit_i")
        out[sym] = dict(name=name, era=era, trades=tr, png=b64)
        won = sum(1 for t in tr if t["ret"] > 0)
        best = max((t["ret"] for t in tr), default=0)
        print(f"  {sym:6s} 신호 {len(tr):2d}회 · 수익 {won}/{len(tr)} · 최고 {best:+.0f}%")
    with open(os.path.join(OUT, "trades.json"), "w", encoding="utf-8") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "png"}
                   for k, v in out.items()}, f, ensure_ascii=False, indent=1)
    print(f"\n→ {OUT}")
    return out


DECK = os.path.join(BASE, "docs", "cards", "leaders_cases.html")

CSS = """
:root{--paper:#e8ebef;--sheet:#fbfcfd;--sheet2:#f1f4f7;--ink:#12161b;--ink2:#39434f;
--mut:#6d7883;--line:#ccd4dd;--hair:#dde3ea;--acc:#17415c;--brass:#8a6a12;--brassbg:#f6f0dc;
--pos:#1f6b45;--posbg:#e2efe7;--neg:#a03028;--negbg:#f8e5e3;--warn:#8a5a10;--warnbg:#faefd9;
--mono:Consolas,"Cascadia Mono","D2Coding",ui-monospace,monospace;
--sans:"Pretendard","Malgun Gothic",-apple-system,"Segoe UI",system-ui,sans-serif;
--sh:0 1px 2px rgba(18,22,27,.05),0 14px 34px -22px rgba(18,22,27,.3)}
@media (prefers-color-scheme:dark){:root{--paper:#0a0d11;--sheet:#141a21;--sheet2:#1b232c;
--ink:#e5eaf0;--ink2:#b3bfcb;--mut:#7f8b98;--line:#2a343f;--hair:#232c35;--acc:#6fa8cc;
--brass:#c9a53f;--brassbg:#2a2415;--pos:#74c295;--posbg:#172a20;--neg:#e0897f;--negbg:#2c1c1a;
--warn:#d5a84e;--warnbg:#2a2415;--sh:0 1px 2px rgba(0,0,0,.5),0 16px 40px -24px rgba(0,0,0,.8)}}
:root[data-theme="dark"]{--paper:#0a0d11;--sheet:#141a21;--sheet2:#1b232c;--ink:#e5eaf0;
--ink2:#b3bfcb;--mut:#7f8b98;--line:#2a343f;--hair:#232c35;--acc:#6fa8cc;--brass:#c9a53f;
--brassbg:#2a2415;--pos:#74c295;--posbg:#172a20;--neg:#e0897f;--negbg:#2c1c1a;--warn:#d5a84e;
--warnbg:#2a2415;--sh:0 1px 2px rgba(0,0,0,.5),0 16px 40px -24px rgba(0,0,0,.8)}
:root[data-theme="light"]{--paper:#e8ebef;--sheet:#fbfcfd;--sheet2:#f1f4f7;--ink:#12161b;
--ink2:#39434f;--mut:#6d7883;--line:#ccd4dd;--hair:#dde3ea;--acc:#17415c;--brass:#8a6a12;
--brassbg:#f6f0dc;--pos:#1f6b45;--posbg:#e2efe7;--neg:#a03028;--negbg:#f8e5e3;--warn:#8a5a10;
--warnbg:#faefd9;--sh:0 1px 2px rgba(18,22,27,.05),0 14px 34px -22px rgba(18,22,27,.3)}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:15px;
line-height:1.7;-webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding:0 14px 70px;display:flex;flex-direction:column;gap:18px}
h1,h2,h3{margin:0;text-wrap:balance}
.top{padding:38px 8px 22px}
.kick{font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;
color:var(--brass);font-weight:700}
.top h1{font-size:clamp(26px,5vw,40px);font-weight:800;letter-spacing:-.03em;line-height:1.1;margin:11px 0}
.top p{color:var(--ink2);max-width:64ch;margin:0}
.meta{display:flex;flex-wrap:wrap;gap:5px 20px;margin-top:16px;padding-top:13px;
border-top:2px solid var(--acc);font-family:var(--mono);font-size:11.5px;color:var(--mut)}
.meta b{color:var(--ink2)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
background:var(--line);border:1px solid var(--line)}
.tile{background:var(--sheet);padding:12px 14px}
.tile .k{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--mut);font-weight:700}
.tile .v{font-family:var(--mono);font-size:23px;font-weight:700;letter-spacing:-.02em;
margin:3px 0 1px;font-variant-numeric:tabular-nums}
.tile .s{font-size:11.5px;color:var(--mut);line-height:1.45}
.box{padding:13px 16px;font-size:13.8px;color:var(--ink2);border-left:3px solid var(--acc);
background:var(--sheet2)}
.box.warn{border-left-color:var(--warn);background:var(--warnbg)}
.box.kill{border-left-color:var(--neg);background:var(--negbg)}
.box.ok{border-left-color:var(--pos);background:var(--posbg)}
.box b{color:var(--ink)}
.card{background:var(--sheet);border:1px solid var(--line);box-shadow:var(--sh);overflow:hidden}
.chead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;
padding:13px 16px;border-bottom:1px solid var(--hair);background:var(--sheet2)}
.ct{display:flex;align-items:baseline;gap:10px}
.tick{font-family:var(--mono);font-size:12px;font-weight:700;letter-spacing:.05em;
color:var(--sheet);background:var(--acc);padding:3px 8px}
.chead h3{font-size:17px;font-weight:700;letter-spacing:-.02em}
.sum{font-family:var(--mono);font-size:11.5px;color:var(--mut);font-variant-numeric:tabular-nums}
.chart img{display:block;width:100%;height:auto}
@media (prefers-color-scheme:dark){.chart img{filter:brightness(.92) contrast(1.04)}}
:root[data-theme="dark"] .chart img{filter:brightness(.92) contrast(1.04)}
:root[data-theme="light"] .chart img{filter:none}
.tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px;min-width:420px}
th,td{padding:5px 10px;text-align:left;border-bottom:1px solid var(--hair)}
thead th{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--mut);font-weight:700;border-bottom:1.5px solid var(--line)}
tbody tr:last-child td{border-bottom:0}
td.n,th.n{font-family:var(--mono);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.pos{color:var(--pos);font-weight:600}.neg{color:var(--neg);font-weight:600}.mut{color:var(--mut)}
footer{font-family:var(--mono);font-size:11px;color:var(--mut);line-height:1.8;padding:0 8px}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def build_deck(out):
    import statistics as st
    allt = [t for v in out.values() for t in v["trades"]]
    r = [t["ret"] for t in allt]
    w = [x for x in r if x > 0]; l = [x for x in r if x <= 0]
    win = len(w) / len(r) * 100
    payoff = st.mean(w) / abs(st.mean(l)) if l else float("nan")
    best = max(allt, key=lambda t: t["ret"])
    nvda = out.get("NVDA", {}).get("trades", [])

    P = []
    P.append(f'<title>주도주 사례 — 규칙⑥은 언제 샀나</title>\n<style>{CSS}</style>\n<div class="wrap">')
    P.append(f'''<header class="top">
  <p class="kick">Case Study · Rule ⑥ Entry Points</p>
  <h1>주도주 사례 —<br>규칙은 실제로 언제 샀나</h1>
  <p>2026-08-02 카드덱은 주도주 25종을 <b>사람 눈으로</b> 해부한 것이었다.
  이번에는 그 사례 위에 <b>확정 규칙⑥의 실제 신호</b>를 얹었다.
  차트의 ▲는 규칙이 매수한 주, ▼는 고점 대비 −20%로 청산한 주다.
  가정도 재량도 없이, 규칙이 그때 냈을 신호 그대로다.</p>
  <div class="meta">
    <span>갱신 <b>2026-08-12</b></span>
    <span>대상 <b>{len(out)}종</b> (미국)</span>
    <span>규칙 <b>RS13&gt;1.5 · (흑자전환 OR 이익폭증) · OPM&gt;0</b></span>
    <span>청산 <b>주봉 고점 −20%</b></span>
  </div>
</header>''')

    P.append(f'''<div class="tiles">
  <div class="tile"><p class="k">신호 거래</p><p class="v">{len(r)}회</p><p class="s">{len(out)}종 · 재진입 포함</p></div>
  <div class="tile"><p class="k">승률</p><p class="v">{win:.1f}%</p><p class="s">유니버스 전체는 43.4%</p></div>
  <div class="tile"><p class="k">평균 / 중앙</p><p class="v">{st.mean(r):+.0f}%</p><p class="s">중앙 {st.median(r):+.1f}% — 격차가 곧 비대칭</p></div>
  <div class="tile"><p class="k">손익비</p><p class="v">{payoff:.1f}</p><p class="s">이긴 거래 평균 ÷ 진 거래 평균</p></div>
  <div class="tile"><p class="k">최고 거래</p><p class="v pos">{best['ret']:+.0f}%</p><p class="s">{best['entry_date']} 진입 · {best['hold_wk']}주</p></div>
</div>''')

    P.append('''<div class="box kill"><b>🔴 이 표본은 승자로 채워져 있다 — 성적을 그대로 믿으면 안 된다.</b>
    여기 13종은 “나중에 크게 오른 종목”이라고 <b>이미 알고</b> 고른 것이다.
    그래서 승률 {:.0f}%·평균 {:+.0f}%가 나오지만, 같은 규칙을 미국 1,271종 전체에 돌리면
    <b>승률 43.4% · 거래 수익 중앙값 −5.9%</b>다.
    이 페이지는 <b>“규칙이 성공한다”의 증거가 아니라 “규칙이 어느 타점에서 작동하는가”의 예시</b>다.</div>'''.format(win, st.mean(r)))

    if nvda:
        t = nvda[0]
        P.append(f'''<div class="box ok"><b>✅ 규칙 전환이 실제로 사각지대를 열었다 — NVDA.</b>
        구 규칙⑤(PSR&lt;3)는 NVDA를 8년 내내 한 번도 잡지 못했다.
        신호 발생 주차의 PSR이 최소 10.5였기 때문이다.
        PSR을 의사결정에서 빼고 OPM&gt;0으로 바꾼 규칙⑥은
        <b>{t['entry_date']}에 진입해 {t['exit_date']}에 청산, {t['ret']:+.1f}% ({t['hold_wk']}주 보유)</b>를 기록한다.
        2026-08-08 결정의 가장 직접적인 증거다.</div>''')

    P.append('''<div class="box warn"><b>이전 카드덱(v2)에서 철회된 결론 두 가지.</b>
    2026-08-02판은 25종 표본에서 <b>“신고가 −15% 이내 진입이 낫다(326% vs 250%)”</b>와
    <b>“주도주는 싸게 시작했다(PSR 중앙 2.4배)”</b>를 결론으로 냈다.
    이후 유니버스 1,271종 검증에서 <b>신고가 근접은 리프트 0.4~0.7로 오히려 불리</b>했고,
    <b>PSR은 주도주의 17%를 구조적으로 배제</b>해 의사결정에서 제외됐다.
    <b>승자 25종에서 찾은 공통점은 패자에게도 있었다.</b> 이 페이지가 표본이 아니라
    규칙을 보여주는 이유다.</div>''')

    for sym, v in out.items():
        tr = v["trades"]
        rr = [t["ret"] for t in tr]
        head = (f"{len(tr)}회 · 최고 {max(rr):+.0f}%" if tr else "신호 없음")
        P.append(f'''<section class="card">
  <div class="chead"><div class="ct"><span class="tick">{sym}</span><h3>{v["name"]} {v["era"]}</h3></div>
  <span class="sum">{head}</span></div>
  <div class="chart"><img alt="{sym} 주봉과 규칙⑥ 진입·청산 시점" src="data:image/png;base64,{v["png"]}"></div>''')
        if tr:
            P.append('<div class="tw"><table><thead><tr><th>진입</th><th>청산</th>'
                     '<th class="n">진입가</th><th class="n">고점</th><th class="n">수익</th>'
                     '<th class="n">보유</th></tr></thead><tbody>')
            for t in tr:
                cls = "pos" if t["ret"] > 0 else "neg"
                ex = t["exit_date"] or '<span class="mut">보유 중</span>'
                P.append(f'<tr><td>{t["entry_date"]}</td><td>{ex}</td>'
                         f'<td class="n">${t["entry_px"]:,.2f}</td><td class="n">${t["peak_px"]:,.2f}</td>'
                         f'<td class="n {cls}">{t["ret"]:+.1f}%</td><td class="n">{t["hold_wk"]}주</td></tr>')
            P.append('</tbody></table></div>')
        else:
            P.append('<div class="box" style="margin:0;border-left:0">'
                     '규칙⑥ 조건을 충족한 주가 한 번도 없었다. '
                     '<b>주도주였다고 해서 규칙이 잡는 것은 아니다.</b></div>')
        P.append('</section>')

    P.append('''<div class="box"><b>이 페이지에서 읽어야 할 것.</b>
    개별 종목의 수익률이 아니라 <b>패턴</b>이다 — 한 종목에서도 규칙은 여러 번 진입하고
    여러 번 손절된다. TSLA는 6번 진입해 4번 손절났고, 남은 한 번이 <b>+557%</b>였다.
    <b>이기는 거래가 드물고 크다는 구조</b>가 사례 단위에서도 그대로 재현된다.
    손절을 지키지 못하면 그 한 번을 만나기 전에 계좌가 먼저 끝난다.</div>''')

    P.append(f'''<footer>주도주 탐지 연구 · 사례 카드덱 · 2026-08-12<br>
    생성 <code>leaders_cases.py</code> · 데이터 <code>factor_weekly</code> (미국 1,271종)<br>
    한국 8종은 DART 잠정실적 공시일 미수집으로 유니버스에서 제외됨.
    SNDK · OKLO · PLUG · SATL은 시총·거래대금 게이트 미달로 데이터 없음.</footer>
</div>''')

    os.makedirs(os.path.dirname(DECK), exist_ok=True)
    with open(DECK, "w", encoding="utf-8") as f:
        f.write("\n".join(P))
    print(f"→ {DECK}  ({os.path.getsize(DECK)//1024} KB)")


if __name__ == "__main__":
    build_deck(main())
