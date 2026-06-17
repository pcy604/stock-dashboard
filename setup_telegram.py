import sys
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print()
print('═══════════════════════════════════════')
print('  텔레그램 봇 설정 도우미')
print('═══════════════════════════════════════')
print()
print('[STEP 1] 텔레그램에서 @BotFather 검색')
print('         /newbot 입력 → 봇 이름 입력 → 토큰 발급')
print()
token = input('  발급받은 BOT TOKEN 입력: ').strip()
print()
print('[STEP 2] 지금 텔레그램에서 방금 만든 봇에게 아무 메시지나 보내세요')
input('  보낸 후 Enter 누르기...')
print()
print('  chat_id 조회 중...')

try:
    r = requests.get(f'https://api.telegram.org/bot{token}/getUpdates', timeout=10)
    data = r.json()

    if not data.get('ok'):
        print(f'  오류: {data}')
        print('  토큰을 다시 확인하세요.')
    elif not data['result']:
        print('  메시지를 찾을 수 없습니다.')
        print('  봇에게 메시지를 보낸 후 다시 실행하세요.')
    else:
        chat_id = str(data['result'][-1]['message']['chat']['id'])
        print(f'  CHAT ID: {chat_id}')
        print()
        print('─' * 45)
        print('  config.py에 아래 내용을 복사하세요:')
        print('─' * 45)
        print(f'  TELEGRAM_ENABLED  = True')
        print(f'  TELEGRAM_TOKEN    = "{token}"')
        print(f'  TELEGRAM_CHAT_ID  = "{chat_id}"')
        print('─' * 45)
        print()

        # 테스트 메시지 전송
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': '✅ 스크리너 봇 연결 성공!\n이제 신호가 여기로 옵니다.'},
            timeout=10
        )
        print('  텔레그램에서 연결 성공 메시지를 확인하세요!')

except Exception as e:
    print(f'  오류: {e}')

print()
input('  완료. Enter를 눌러 닫기...')
