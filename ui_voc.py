# -*- coding: utf-8 -*-
"""💬 VOC 탭 (2026-11-20, 차니 요구 4 — '기능 개선 요청 자유자재로') — 저장은 voc_store.

접수 폼(영역·분류·제목·내용) → 공개 목록(상태 필터) → 한 건 상세(공감 · 소유자는 상태·답변 변경).
소유자 화면에서 '진행' 으로 바꾼 건은 개발 작업 목록이 된다(경영실 이슈와 별개 — 사용자 목소리 원문 보관용).
"""
import pandas as pd
import streamlit.components.v1 as components

import voc_store as V

VERSION = '2026-11-20b'   # b: 이미지 첨부 · Ctrl+V 붙여넣기

# 캡처 → Ctrl+V: 화면 어디서 붙여도 클립보드 이미지를 첨부칸(.st-key-voc_img)의 파일 입력에 넣는다.
# components.html 은 같은 출처 iframe 이라 부모 문서에 붙을 수 있다. 리스너는 창당 한 번만(재실행마다 쌓이지 않게).
# 이미지가 없는 붙여넣기(글자)는 건드리지 않는다.
_PASTE_JS = """<script>
(function(){
  const w = window.parent, d = w.document;
  if (w.__vocPaste) return; w.__vocPaste = true;
  d.addEventListener('paste', function(e){
    const inp = d.querySelector('.st-key-voc_img input[type=file]');
    if (!inp || !e.clipboardData) return;
    const files = [...e.clipboardData.items].filter(i => i.kind === 'file' && i.type.startsWith('image/')).map(i => i.getAsFile());
    if (!files.length) return;
    e.preventDefault();
    const dt = new DataTransfer();
    const ts = new Date().toISOString().slice(11,19).replace(/:/g,'');
    files.forEach((f, n) => dt.items.add(new File([f], `capture_${ts}_${n+1}.png`, {type: f.type || 'image/png'})));
    inp.files = dt.files;
    inp.dispatchEvent(new Event('change', {bubbles: true}));
  }, true);
})();
</script>"""


def render(st, areas: list, is_owner: bool, uid: str):
    display = '회원' if str(uid).startswith('u_') else '익명'      # access.uid(): 로그인 u_해시 · 비로그인 s_세션
    st.markdown('#### 💬 VOC — 기능 요청 · 개선 · 버그 제보')
    st.caption('불편한 점·있었으면 하는 기능·틀린 데이터를 남겨 주십시오. 접수 → 검토 → 진행 → 완료 순으로 처리 상태와 답변이 이 목록에 공개됩니다.')
    if not V.ready():
        st.info('저장소가 설정되지 않아 접수할 수 없습니다(secrets [store]).')
        return
    with st.form('voc_form', clear_on_submit=True):
        c1, c2 = st.columns(2)
        area = c1.segmented_control('영역', ['전체'] + list(areas), default='전체', key='voc_area') or '전체'
        kind = c2.segmented_control('분류', V.KINDS, default=V.KINDS[0], key='voc_kind') or V.KINDS[0]
        title = st.text_input('제목', max_chars=V.MAX_TITLE, placeholder='예) 종목 발굴 표에 배당수익률 열 추가')
        body = st.text_area('내용 (선택)', max_chars=V.MAX_BODY, height=100,
                            placeholder='어떤 화면에서 · 무엇이 · 어떻게 되면 좋겠는지. 버그면 재현 순서.')
        imgs = st.file_uploader(f'이미지 첨부 — 캡처 후 이 화면에서 Ctrl+V (최대 {V.MAX_IMG}장)', type=['png', 'jpg', 'jpeg', 'webp'],
                                accept_multiple_files=True, key='voc_img')
        st.caption('공개 게시판입니다 — 계좌번호·잔고·개인정보가 보이는 캡처는 가리고 올려 주십시오.')
        if st.form_submit_button('📨 보내기'):
            try:
                V.clean(area, kind, title, body)                 # 이미지 올리기 전에 글 검증(헛업로드 방지)
                urls = [V.upload(f.getvalue()) for f in (imgs or [])[:V.MAX_IMG]]
                V.submit(uid, display, area, kind, title, body, images=urls)
                st.success('접수했습니다. 아래 목록에서 상태를 확인할 수 있습니다.')
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f'접수 실패: {type(e).__name__}')
    components.html(_PASTE_JS, height=0)
    try:
        rows = V.items()
    except Exception as e:
        st.caption(f'`VOC 목록을 읽지 못했습니다: {type(e).__name__}`')
        return
    if not rows:
        st.caption('아직 접수된 의견이 없습니다.')
        return
    df = pd.DataFrame(rows)
    df['등록일'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d')
    k = st.columns(4)
    k[0].metric('전체', f'{len(df):,}건')
    for col, s in zip(k[1:], ('접수', '진행', '완료')):
        col.metric(s, f"{int((df['status'] == s).sum()):,}건")
    flt = st.segmented_control('상태', ['전체'] + V.STATUS, default='전체', key='voc_flt') or '전체'
    view = df if flt == '전체' else df[df['status'] == flt]
    show = view[['id', 'kind', 'area', 'title', 'status', 'votes', '등록일']].rename(
        columns={'id': '번호', 'kind': '분류', 'area': '영역', 'title': '제목', 'status': '상태', 'votes': '공감(건)'})
    st.dataframe(show, hide_index=True, src='voc_store(Supabase) · 이용자 접수', asof=df['등록일'].max())
    if view.empty:
        return
    opts = view['id'].tolist()
    vid = st.selectbox('자세히 볼 번호', opts, format_func=lambda i: f"#{i} · {view.set_index('id').at[i, 'title']}", key='voc_sel')
    r = view.set_index('id').loc[vid]
    st.markdown(f"**#{vid} {r['title']}** · {r['kind']} · {r['area']} · {r['status']} · {r['display'] or '익명'} · {r['등록일']}")
    if r.get('body'):
        st.markdown(f"> {r['body']}")
    pics = [u for u in (r.get('images') if isinstance(r.get('images'), list) else []) if u]
    if pics:
        for col, u in zip(st.columns(V.MAX_IMG), pics):
            col.image(u)
    if r.get('reply'):
        st.markdown(f"**답변** — {r['reply']}")
    voted = st.session_state.setdefault('voc_voted', set())
    if st.button(f"👍 나도 필요해요 ({int(r['votes'] or 0)})", disabled=vid in voted, key=f'voc_v|{vid}'):
        try:
            V.vote(vid, int(r['votes'] or 0))
            voted.add(vid)
            st.rerun()
        except Exception as e:
            st.caption(f'`공감 실패: {type(e).__name__}`')
    if is_owner:
        with st.container(border=True):
            st.caption('🔒 소유자 — 상태·답변')
            c1, c2 = st.columns([2, 3])
            ns = c1.segmented_control('상태 변경', V.STATUS, default=r['status'] if r['status'] in V.STATUS else V.STATUS[0],
                                      key=f'voc_s|{vid}') or r['status']
            rep = c2.text_input('답변(공개)', value=r.get('reply') or '', key=f'voc_r|{vid}')
            if st.button('저장', key=f'voc_save|{vid}'):
                try:
                    V.set_status(vid, ns, rep)
                    st.rerun()
                except Exception as e:
                    st.error(f'저장 실패: {type(e).__name__}')
