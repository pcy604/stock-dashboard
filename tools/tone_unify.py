# -*- coding: utf-8 -*-
"""
화면 문구 말투 통일 — 평서체(~이다) → 경어체(~입니다)  (2026-09-10)

왜
  화면에 나가는 문장이 두 말투로 섞여 있었다. 같은 화면 안에서
  "이 분포는 U자다"와 "확인하세요"가 나란히 떴다. 형 요청:
  "~이다, ~같다, ~때문이다 말투 별로야. 모든 말투 통일화 시켜"

범위
  st.markdown / caption / warning / info / error / success / write 안의 문자열만.
  **코드 주석은 건드리지 않는다** — 화면에 안 나가고, 주석은 짧은 평서체가 읽기 낫다.

안전 규칙
  문장 끝(마침표·따옴표·줄바꿈 직전)만 바꾼다. 문장 중간의 "~다"는 그대로 둔다.
  예: "판단한다는 뜻" 은 안 건드리고, "판단한다." 만 "판단합니다." 로.

CLI
  python tools/tone_unify.py --dry     # 바뀔 것만 보여준다
  python tools/tone_unify.py --apply   # 실제 적용
"""
import io
import re
import sys

TARGET = "dashboard.py"

# (평서체 어미, 경어체 어미) — 긴 것부터 매칭해야 한다
RULES = [
    ("때문이다", "때문입니다"), ("뿐이다", "뿐입니다"), ("것이다", "것입니다"),
    ("아니다", "아닙니다"), ("이다", "입니다"),
    ("없앴다", "없앴습니다"), ("없다", "없습니다"), ("있다", "있습니다"),
    ("같다", "같습니다"), ("낫다", "낫습니다"), ("맞다", "맞습니다"),
    ("작다", "작습니다"), ("크다", "큽니다"), ("적다", "적습니다"), ("많다", "많습니다"),
    ("높다", "높습니다"), ("낮다", "낮습니다"), ("좋다", "좋습니다"), ("나쁘다", "나쁩니다"),
    ("빠르다", "빠릅니다"), ("느리다", "느립니다"), ("드물다", "드뭅니다"),
    ("어렵다", "어렵습니다"), ("쉽다", "쉽습니다"), ("얇다", "얇습니다"),
    ("한다", "합니다"), ("된다", "됩니다"), ("본다", "봅니다"), ("든다", "듭니다"),
    ("난다", "납니다"), ("간다", "갑니다"), ("온다", "옵니다"), ("준다", "줍니다"),
    ("만든다", "만듭니다"), ("잡는다", "잡습니다"), ("띄운다", "띄웁니다"),
    ("쓴다", "씁니다"), ("읽는다", "읽습니다"), ("찍는다", "찍습니다"),
    ("넘는다", "넘습니다"), ("줄인다", "줄입니다"), ("늘린다", "늘립니다"),
    ("걸린다", "걸립니다"), ("빠진다", "빠집니다"), ("바뀐다", "바뀝니다"),
    ("떨어진다", "떨어집니다"), ("올라간다", "올라갑니다"), ("내려간다", "내려갑니다"),
    ("돌린다", "돌립니다"), ("돈다", "돕니다"), ("죽는다", "죽습니다"),
    ("이긴다", "이깁니다"), ("진다", "집니다"), ("샀다", "샀습니다"),
    ("갈린다", "갈립니다"), ("뜻이다", "뜻입니다"), ("말이다", "말입니다"),
    ("셈이다", "셈입니다"), ("탓이다", "탓입니다"),
]
# 문장 끝 판정 — 마침표 · 대시(—) · 큰따옴표 · 닫는 괄호 · 줄 끝
TAIL = r'(?=\.|\s*—|\s*"|\s*\)|\s*$)'
# ⚠️ 작은따옴표는 뺐다. 한국어 인용("'섹션이 바뀐다'는 신호")에서 문장 중간을
#    문장 끝으로 오인해 '바뀝니다는' 같은 걸 만든다.

ST_CALL = re.compile(r'st\.(markdown|caption|warning|info|error|success|write)\(')


def convert_line(line):
    """그 줄이 화면 문자열을 담고 있으면 어미를 바꾼다."""
    out, n = line, 0
    for a, b in RULES:
        pat = re.compile(re.escape(a) + TAIL)
        out, k = pat.subn(b, out)
        n += k
    return out, n


def main():
    apply_ = "--apply" in sys.argv
    lines = io.open(TARGET, encoding="utf-8").read().split("\n")
    inside = False          # 여러 줄에 걸친 st.*(...) 안인가
    in_css = False
    depth = 0
    changed, total = [], 0
    for i, l in enumerate(lines):
        # <style> 블록은 화면 문구가 아니라 CSS 다 — 건드리지 않는다
        if '<style>' in l:
            in_css = True
        if '</style>' in l:
            in_css = False
            continue
        if in_css:
            continue
        if ST_CALL.search(l):
            inside = True
            depth = l.count("(") - l.count(")")
        elif inside:
            depth += l.count("(") - l.count(")")
        if not inside:
            continue
        # 문자열이 있는 줄만
        if '"' in l or "'" in l:
            new, n = convert_line(l)
            if n:
                changed.append((i + 1, l.strip()[:88], new.strip()[:88]))
                lines[i] = new
                total += n
        if inside and depth <= 0:
            inside = False

    print(f"바뀌는 줄 {len(changed)}개 · 어미 {total}곳")
    for ln, a, b in changed[:20]:
        print(f"  {ln}: {a}")
        print(f"     → {b}")
    if len(changed) > 20:
        print(f"  … 그리고 {len(changed) - 20}줄 더")

    if apply_:
        import ast
        src = "\n".join(lines)
        ast.parse(src)                      # 검증 먼저
        io.open(TARGET, "w", encoding="utf-8").write(src)
        print(f"\n적용 완료 — {TARGET}")
    else:
        print("\n(미리보기다. 적용하려면 --apply)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
