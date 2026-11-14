import chatbot as C


def test_find_syms_skips_common_words():
    assert [x['sym'] for x in C._find_syms('AI 반도체 중 AMD 는?')] == ['AMD']


def test_context_has_site_data_and_cap():
    c = C.context('삼성전자 어때')
    assert '005930' in c and len(c) <= 14000


def test_ask_without_keys_raises():
    try:
        C.ask('코스피?', gemini_key='', groq_key='')
    except RuntimeError:
        return
    assert False
