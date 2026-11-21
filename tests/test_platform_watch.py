# -*- coding: utf-8 -*-
"""플랫폼 상시 감시 + 감시 커버리지 정답 테스트 (2026-11-22).

감시자를 테스트하는 이유 — 감시자가 조용히 고장나면 **고장이 없는 것처럼 보인다.**
이 저장소에서 실제로 세 번 그랬다:
  · daily-refresh 단계가 19일 죽었는데 continue-on-error 로 초록불
  · 주간 산출물 감시를 leaders_weekly 가 맡고 있었는데 그 스크립트가 /tmp 버그로 죽어 있었다
  · weekly-profile 의 신선도 검사가 job 완전일치라 9개 중 7개만 봤고, always() 가 없어
    앞 단계가 죽으면 같이 건너뛰었다
그래서 '감시자가 실제로 울리는가'를 숫자로 박는다.
"""
import importlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import platform_watch as P        # noqa: E402
import check_freshness_ci as C    # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# 레지스트리 자체의 일관성
# ──────────────────────────────────────────────────────────────────────
def test_every_platform_declares_impact_and_fallback():
    """경보를 받은 사람이 '그래서 뭐가 멈추나 · 대체는 뭔가'를 바로 알아야 한다.
    비어 있으면 경보가 와도 판단이 안 되고, 판단이 안 되는 경보는 무시된다."""
    for p in P.PLATFORMS:
        assert p.get("breaks"), f"{p['name']}: breaks 없음"
        assert p.get("fallback"), f"{p['name']}: fallback 없음 ('없음'이라고 적는 것도 답이다)"
        assert p.get("review"), f"{p['name']}: L3 에서 물을 것(review) 없음"


def test_kinds_have_the_fields_they_need():
    for p in P.PLATFORMS:
        if p["kind"] == "probe":
            assert p.get("probe", "").startswith("https://"), p["name"]
        elif p["kind"] == "indirect":
            assert p.get("indirect"), f"{p['name']}: 간접 판정에 쓸 산출물 경로가 없다"
        else:
            assert p["kind"] == "manual", p["kind"]


def test_indirect_paths_are_registered_outputs():
    """간접 판정은 산출물 신선도로 한다 — 그 경로가 레지스트리에 없으면 늘 'missing' 이 되어
    멀쩡한 플랫폼을 죽었다고 보고한다."""
    import data_freshness as F
    known = {s["path"] for s in F.SOURCES}
    for p in P.PLATFORMS:
        for rel in p.get("indirect") or []:
            assert rel in known, f"{p['name']}: {rel} 가 data_freshness.SOURCES 에 없다"


def test_auth_env_names_are_real_secrets():
    """auth 에 적은 환경변수가 실제로 워크플로가 주는 이름이어야 한다.
    오타면 영원히 '비밀값 없음 — 도달만 확인' 으로 떨어져 **자격 끊김을 못 본다.**"""
    import glob
    import re
    names = set()
    for f in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")):
        names |= set(re.findall(r"secrets\.([A-Z_]+)", open(f, encoding="utf-8").read()))
    for p in P.PLATFORMS:
        if p.get("auth"):
            assert p["auth"][0] in names, f"{p['name']}: secrets.{p['auth'][0]} 가 어느 워크플로에도 없다"
        if p.get("doc_ua"):
            assert p["doc_ua"] in names, f"{p['name']}: secrets.{p['doc_ua']} 가 없다"


def test_platform_watch_is_wired_to_a_workflow():
    """도구만 만들어 놓고 크론에 안 걸면 감시는 0 이다 — 이 저장소에서 두 번 그랬다."""
    y = open(os.path.join(ROOT, ".github", "workflows", "platform-watch.yml"), encoding="utf-8").read()
    for flag in ("--l1", "--l2", "--l3"):
        assert f"platform_watch.py {flag}" in y, f"워크플로에 {flag} 호출이 없다"
    assert "schedule:" in y


# ──────────────────────────────────────────────────────────────────────
# L1 — 상태 판정
# ──────────────────────────────────────────────────────────────────────
def _p(**kw):
    base = dict(name="T", kind="probe", used_for="x", probe="https://x/", breaks="b", fallback="f", review="r")
    base.update(kw)
    return base


def test_probe_no_auth_200_is_ok(monkeypatch):
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (True, 200, ""))
    assert P._probe(_p())[0] == "ok"


def test_probe_no_auth_403_is_reachable_not_ok(monkeypatch):
    """비밀값이 필요 없는 공개 엔드포인트가 403 이면 '도달은 하나 쓸 수 있는지는 모름'이다.
    여기서 'ok' 를 주면 차단당한 상태가 초록불이 된다."""
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (True, 403, ""))
    assert P._probe(_p())[0] == "reachable"


def test_probe_with_key_rejected_is_authfail(monkeypatch):
    """키가 있는데 403 → **우리 자격이 끊겼다.** 서버 장애와 구분해야 즉시 경보할 수 있다."""
    monkeypatch.setenv("TESTKEY", "abc")
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (True, 403, ""))
    assert P._probe(_p(auth=("TESTKEY", "https://x/?key={key}")))[0] == "authfail"


def test_probe_without_key_falls_back_to_reachability(monkeypatch):
    monkeypatch.delenv("TESTKEY", raising=False)
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (True, 401, ""))
    state, why = P._probe(_p(auth=("TESTKEY", "https://x/?key={key}")))
    assert state == "reachable" and "TESTKEY" in why


def test_probe_connection_error_is_down(monkeypatch):
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (False, "URLError", ""))
    assert P._probe(_p())[0] == "down"


def test_key_is_url_quoted(monkeypatch):
    """키에 & 나 ? 가 들어 있으면 그대로 붙이면 URL 이 깨져 **멀쩡한 키를 authfail 로 신고**한다."""
    seen = {}
    monkeypatch.setenv("TESTKEY", "a&b=c")
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (seen.update(u=u), (True, 200, ""))[1])
    P._probe(_p(auth=("TESTKEY", "https://x/?key={key}")))
    assert "a%26b%3Dc" in seen["u"]


def test_sec_contact_goes_into_user_agent(monkeypatch):
    """SEC 는 키가 아니라 **연락처를 User-Agent 에** 실어야 한다. 쿼리로 붙이면 영원히 403 이다."""
    seen = {}
    monkeypatch.setenv("SEC_CONTACT", "me@example.com")
    monkeypatch.setattr(P, "_get",
                        lambda u, want_text=False, ua=None: (seen.update(ua=ua), (True, 200, ""))[1])
    P._probe(_p(auth=("SEC_CONTACT", "https://data.sec.gov/x")))
    assert seen["ua"] == "me@example.com"


@pytest.mark.parametrize("state,grows", [("down", True), ("authfail", True), ("ok", False), ("reachable", False)])
def test_streak_counts_only_real_failures(tmp_path, monkeypatch, state, grows):
    """'reachable'(비밀값 없어 못 재 봄)을 실패로 세면 로컬·비밀값 없는 러너가 매번 빨간불이 되고,
    그러면 사람이 경보를 끈다 — 감시가 사라진다."""
    monkeypatch.setattr(P, "STATUS", str(tmp_path / "s.json"))
    json.dump({"platforms": {"T": {"streak": 2}}}, open(P.STATUS, "w", encoding="utf-8"))
    monkeypatch.setattr(P, "PLATFORMS", [_p()])
    monkeypatch.setattr(P, "_probe", lambda p: (state, "why"))
    P.l1(warn_only=True)
    got = json.load(open(P.STATUS, encoding="utf-8"))["platforms"]["T"]["streak"]
    assert (got == 3) if grows else (got == 0)


def test_authfail_alarms_immediately(tmp_path, monkeypatch, capsys):
    """자격 거부는 일시 장애가 아니다 — 3회를 기다리면 3일을 잃는다."""
    monkeypatch.setattr(P, "STATUS", str(tmp_path / "s.json"))
    monkeypatch.setattr(P, "PLATFORMS", [_p()])
    monkeypatch.setattr(P, "_probe", lambda p: ("authfail", "HTTP 403"))
    assert P.l1() == 1
    assert "::error::" in capsys.readouterr().out


def test_down_waits_for_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "STATUS", str(tmp_path / "s.json"))
    monkeypatch.setattr(P, "PLATFORMS", [_p()])
    monkeypatch.setattr(P, "_probe", lambda p: ("down", "URLError"))
    for i in range(1, P.FAIL_STREAK):
        assert P.l1() == 0, f"{i}회에서 울렸다 — 외부 일시 장애로 빨간불이 된다"
    assert P.l1() == 1


# ──────────────────────────────────────────────────────────────────────
# L2 — 규정 문서 diff
# ──────────────────────────────────────────────────────────────────────
def test_text_lines_strips_script_and_tags():
    html = "<html><head><style>a{}</style><script>var x=1</script></head><body><p>Rate limit is 10</p>\n<div>  ok  </div></body></html>"
    got = P._text_lines(html)
    assert "Rate limit is 10" in got
    assert not any("var x" in g or "a{}" in g for g in got)


def test_noteworthy_picks_only_keyword_lines():
    lines = ["Welcome to our site", "The rate limit is 10 per second", "사용 한도를 넘으면 차단됩니다", "Blog"]
    got = P._noteworthy(lines)
    assert len(got) == 2 and "rate limit" in got[0].lower()


def test_noteworthy_truncates_long_lines():
    assert len(P._noteworthy(["limit " + "x" * 5000])[0]) == P.MAX_LINE


def _l2(monkeypatch, tmp_path, body, docs=None):
    monkeypatch.setattr(P, "DOCS", str(tmp_path / "d.json"))
    if docs is not None:
        json.dump({"docs": docs}, open(P.DOCS, "w", encoding="utf-8"), ensure_ascii=False)
    monkeypatch.setattr(P, "PLATFORMS", [_p(docs=["https://x/tos"])])
    monkeypatch.setattr(P, "_get", lambda u, want_text=False, ua=None: (True, 200, body))
    code = P.l2(warn_only=False)
    return code, json.load(open(P.DOCS, encoding="utf-8"))["docs"]


def _body(n=40, extra=""):
    return "<body>" + "".join(f"<p>line {i} of the document</p>" for i in range(n)) + extra + "</body>"


def test_l2_first_run_stores_baseline_and_does_not_alarm(monkeypatch, tmp_path):
    code, docs = _l2(monkeypatch, tmp_path, _body(40, "<p>rate limit is 10 per second</p>"))
    assert code == 0
    assert docs["https://x/tos"]["key_lines"] == ["rate limit is 10 per second"]


def test_l2_same_content_no_alarm(monkeypatch, tmp_path):
    b = _body(40, "<p>rate limit is 10 per second</p>")
    _l2(monkeypatch, tmp_path, b)
    code, _ = _l2(monkeypatch, tmp_path, b, docs=json.load(open(P.DOCS, encoding="utf-8"))["docs"])
    assert code == 0


def test_l2_alarms_when_a_limit_line_changes(monkeypatch, tmp_path):
    """한도 숫자가 10 → 3 으로 바뀌면 울려야 한다. 이게 이 층의 존재 이유다."""
    _, docs = _l2(monkeypatch, tmp_path, _body(40, "<p>rate limit is 10 per second</p>"))
    code, after = _l2(monkeypatch, tmp_path, _body(40, "<p>rate limit is 3 per second</p>"), docs=docs)
    assert code == 1
    assert any("3 per second" in d for d in after["https://x/tos"]["last_diff"])


def test_l2_does_not_alarm_on_cosmetic_change(monkeypatch, tmp_path):
    """공지 배너·문구 교체로 매주 울리면 사람이 안 본다 — 그때부터 감시는 0 이다."""
    _, docs = _l2(monkeypatch, tmp_path, _body(40, "<p>rate limit is 10 per second</p>"))
    code, _ = _l2(monkeypatch, tmp_path,
                  _body(40, "<p>rate limit is 10 per second</p><p>Black Friday sale banner</p>"), docs=docs)
    assert code == 0


def test_l2_refuses_to_store_js_rendered_doc(monkeypatch, tmp_path):
    """정적 HTML 에 1~2줄만 있는 문서를 기준선으로 저장하면 영원히 '변경 없음' — 감시하는 척이다."""
    code, docs = _l2(monkeypatch, tmp_path, "<body><p>Loading…</p></body>")
    assert docs == {}
    assert code == 0            # 저장은 안 하되 빌드를 세우지는 않는다(경고로 부른다)


def test_l2_file_is_byte_stable_without_changes(monkeypatch, tmp_path):
    """파일에 실행 날짜를 쓰면 문서가 안 바뀐 주에도 매번 커밋돼 저장소가 불어난다."""
    b = _body(40, "<p>rate limit is 10 per second</p>")
    _l2(monkeypatch, tmp_path, b)
    first = open(P.DOCS, encoding="utf-8").read()
    _l2(monkeypatch, tmp_path, b, docs=json.load(open(P.DOCS, encoding="utf-8"))["docs"])
    assert open(P.DOCS, encoding="utf-8").read() == first


# ──────────────────────────────────────────────────────────────────────
# 감시 커버리지 (check_freshness_ci)
# ──────────────────────────────────────────────────────────────────────
def test_no_watchdog_hole():
    """운영 주기 산출물에 CI 감시자가 하나도 없으면 실패. 주간 산출물이 이 구멍으로 새어 나갔다."""
    assert C.audit(strict=True) == 0, "감시자가 없는 산출물이 생겼다 — 위 출력의 HOLE 을 보라"


def test_hardcoded_mtime_list_is_also_in_registry():
    """mtime 목록(CHECK)과 레지스트리가 갈라지면 둘 다 반만 맞는다."""
    import data_freshness as F
    known = {s["path"] for s in F.SOURCES}
    missing = [rel for rel, _ in C.CHECK if rel not in known]
    assert not missing, f"CHECK 에만 있고 data_freshness.SOURCES 에 없는 경로: {missing}"


def test_unknown_job_name_fails_loudly(capsys):
    """job 이름이 바뀌었을 때 '해당 산출물 0개 → 통과' 로 조용히 넘어가면 감시가 사라진다."""
    assert C.by_job("존재하지않는잡") == 1
    assert "확인하라" in capsys.readouterr().out


def test_weekly_workflows_call_the_gate():
    """도구가 있어도 워크플로가 안 부르면 0 이다. weekly 가 정확히 이 상태였다."""
    for wf, job in (("weekly-accel", "weekly-accel"), ("weekly-profile", "weekly-profile"),
                    ("daily-refresh", "daily-refresh")):
        y = open(os.path.join(ROOT, ".github", "workflows", f"{wf}.yml"), encoding="utf-8").read()
        assert f"check_freshness_ci.py --job {job}" in y, f"{wf}.yml 에 신선도 게이트가 없다"
        assert "if: always()" in y, f"{wf}.yml: 앞 단계가 죽으면 감시자가 같이 건너뛴다"


def test_registry_module_reloads_clean():
    importlib.reload(P)
    assert len(P.PLATFORMS) >= 10
