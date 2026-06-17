' 대시보드(Streamlit)를 창 없이 백그라운드로 실행
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\lg\Desktop\stock_screener"
sh.Run "cmd /c python -m streamlit run dashboard.py --server.headless=true", 0, False
