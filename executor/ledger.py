"""원장 — 계좌의 진실은 여기 하나. 토스 잔고와 매주 대조한다(P2)."""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger.json")


@dataclass
class Position:
    sym: str
    sleeve: str                 # core | satellite | legacy
    qty: float
    entry_date: str
    entry_px: float
    peak_px: float
    peak_week: str              # 진입 후 최고가(주봉 종가)를 찍은 주
    weeks_held: int = 0
    last_px: float = 0.0
    missing_weeks: int = 0      # 가격을 못 받은 연속 주수(상장폐지·거래정지 감지)


@dataclass
class Ledger:
    cash: float
    positions: Dict[str, Position] = field(default_factory=dict)
    equity_peak: float = 0.0
    sat_equity_peak: float = 0.0
    history: List[dict] = field(default_factory=list)
    last_rebalance_week: Optional[str] = None
    week: Optional[str] = None

    @staticmethod
    def load(path=LEDGER, cash0=0.0):
        if not os.path.exists(path):
            return Ledger(cash=cash0)
        d = json.load(open(path, encoding="utf-8"))
        d["positions"] = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        return Ledger(**d)

    def save(self, path=LEDGER):
        d = asdict(self)
        tmp = path + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def value(self, prices, sleeve=None):
        v = 0.0
        for p in self.positions.values():
            if sleeve and p.sleeve != sleeve:
                continue
            v += p.qty * prices.get(p.sym, p.last_px)
        return v

    def equity(self, prices):
        return self.cash + self.value(prices)
