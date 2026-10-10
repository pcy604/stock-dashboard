set -e
PY=/c/Users/lg/AppData/Local/Python/bin/python.exe
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
echo "=== [1/3] FETCH  $(date +%H:%M:%S) ==="
$PY leaders_build.py fetch 1500
echo "=== [2/3] BUILD  $(date +%H:%M:%S) ==="
$PY leaders_build.py build
echo "=== [3/3] WINNER $(date +%H:%M:%S) ==="
$PY leaders_winner.py
echo "=== DONE $(date +%H:%M:%S) ==="
