@echo off
setlocal

REM ============================================================
REM  茅ヶ崎サーフィン予報 - Windows タスクスケジューラ登録スクリプト
REM  【管理者として実行してください】
REM ============================================================

REM --- 設定 ---------------------------------------------------
REM アプリのフォルダパス（このバッチファイルと同じ場所に自動設定）
set APP_DIR=%~dp0

REM Python 実行ファイルのパス（変更が必要な場合は書き換えてください）
REM  例: C:\Users\yfuru\AppData\Local\Programs\Python\Python312\python.exe
for /f "delims=" %%i in ('where python') do set PYTHON_PATH=%%i

REM タスク名
set TASK_NAME=SurfForecast_Chigasaki

REM 実行時刻（毎日 HH:MM に送信）
set SEND_TIME=18:00
REM ------------------------------------------------------------

echo.
echo ===================================================
echo  Python: %PYTHON_PATH%
echo  アプリ: %APP_DIR%main.py
echo  実行時刻: 毎日 %SEND_TIME%
echo  タスク名: %TASK_NAME%
echo ===================================================
echo.

REM 既存タスクがあれば削除
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM タスクを登録
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON_PATH%\" \"%APP_DIR%main.py\"" ^
  /sc DAILY ^
  /st %SEND_TIME% ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %errorlevel% == 0 (
    echo.
    echo [OK] タスクスケジューラへの登録が完了しました。
    echo      毎日 %SEND_TIME% に自動で通知が送られます。
) else (
    echo.
    echo [ERROR] 登録に失敗しました。管理者として実行してください。
)

echo.
echo タスクの確認コマンド:
echo   schtasks /query /tn "%TASK_NAME%"
echo.
echo 手動実行コマンド（テスト）:
echo   schtasks /run /tn "%TASK_NAME%"
echo.

pause
