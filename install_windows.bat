@echo off
setlocal EnableDelayedExpansion
title NexaCrew - Windows installer (fully automatic)
rem ============================================================
rem  NexaCrew - Virtual Company AI Agent Platform
rem  Fully automatic installer: Python, Node.js/npm, Git,
rem  VS Code, Codex CLI, Claude Code CLI, firewall, launch.
rem  No manual steps required. Safe to re-run (idempotent).
rem ============================================================

rem ---- self-elevate to Administrator (needed for winget/firewall) ----
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator rights...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList 'ELEVATED'"
  exit /b 0
)

set "HERE=%~dp0"
cd /d "%HERE%"
set "LOG=%HERE%install_windows.log"
echo NexaCrew install started %date% %time% > "%LOG%"

echo ==============================================================
echo   NexaCrew - fully automatic installation (Windows)
echo   Log: %LOG%
echo ==============================================================

rem ---- [1/7] package manager: winget (App Installer) ----
echo [1/7] Checking winget package manager...
where winget >nul 2>&1
if %errorlevel% neq 0 (
  echo   winget missing - installing App Installer from Microsoft...
  powershell -NoProfile -Command "Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" >>"%LOG%" 2>&1
)
where winget >nul 2>&1 || echo   NOTE: winget unavailable - will use direct downloads where needed.

rem ---- [2/7] Python 3.12+ (strict: anything older is replaced) ----
echo [2/7] Ensuring Python 3.12+ ...
set "PYEXE="
for %%P in (python.exe) do if not defined PYEXE set "PYEXE=%%~$PATH:P"
if defined PYEXE (
  "%PYEXE%" -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1 || set "PYEXE="
)
rem also accept the 'py' launcher if it can serve 3.12+
if not defined PYEXE (
  py -3.12 -c "import sys; sys.exit(0)" >nul 2>&1 && set "PYEXE=py312"
)
if not defined PYEXE (
  echo   Installing Python 3.12 silently...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements >>"%LOG%" 2>&1
  if !errorlevel! neq 0 (
    echo   winget failed - downloading python.org installer...
    powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile $env:TEMP+'\py312.exe'" >>"%LOG%" 2>&1
    "%TEMP%\py312.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 >>"%LOG%" 2>&1
  )
  rem refresh PATH for this session
  for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "PATH=%%B;%PATH%"
)

rem ---- [3/7] Node.js LTS + npm ----
echo [3/7] Ensuring Node.js LTS + npm ...
where node >nul 2>&1
if %errorlevel% neq 0 (
  winget install -e --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements >>"%LOG%" 2>&1
  for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "PATH=%%B;%PATH%"
)
rem NOTE: npm is a .cmd batch script - it MUST be invoked with CALL, otherwise
rem it takes over this installer and the remaining steps never run.
where node >nul 2>&1 && node --version >>"%LOG%" 2>&1
where npm  >nul 2>&1 && call npm --version >>"%LOG%" 2>&1

rem ---- [4/7] Git + VS Code ----
echo [4/7] Ensuring Git and Visual Studio Code ...
where git >nul 2>&1 || winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements >>"%LOG%" 2>&1
where code >nul 2>&1 || winget install -e --id Microsoft.VisualStudioCode --silent --accept-package-agreements --accept-source-agreements >>"%LOG%" 2>&1
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "PATH=%%B;%PATH%"

rem ---- [5/7] AI CLIs: Codex + Claude Code ----
echo [5/7] Installing Codex CLI and Claude Code CLI (global npm) ...
where npm >nul 2>&1
if %errorlevel% equ 0 (
  echo   installing @openai/codex ...
  call npm install -g @openai/codex >>"%LOG%" 2>&1
  echo   installing @anthropic-ai/claude-code ...
  call npm install -g @anthropic-ai/claude-code >>"%LOG%" 2>&1
) else (
  echo   npm not on PATH yet - the platform installs the CLIs itself on first start.
)

rem ---- [6/7] firewall + permissions ----
echo [6/7] Configuring firewall (port 8600) ...
netsh advfirewall firewall show rule name="NexaCrew Platform" >nul 2>&1 || ^
netsh advfirewall firewall add rule name="NexaCrew Platform" dir=in action=allow protocol=TCP localport=8600 >>"%LOG%" 2>&1

rem ---- [7/7] Python env + launch (start.py installs requirements itself) ----
echo [7/7] Creating environment and starting the platform ...
rem refresh PATH once more so a just-installed Python is visible
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "PATH=%%B;%PATH%"
rem pick an interpreter that is REALLY 3.12+ (never launch with an older one)
set "RUNPY="
py -3.12 -c "import sys; sys.exit(0)" >nul 2>&1 && set "RUNPY=py -3.12"
if not defined RUNPY (
  where python >nul 2>&1 && (
    python -c "import sys; sys.exit(0 if sys.version_info>=(3,12) else 1)" >nul 2>&1 && set "RUNPY=python"
  )
)
if not defined RUNPY (
  for %%D in ("%ProgramFiles%\Python312" "%LocalAppData%\Programs\Python\Python312") do (
    if exist "%%~D\python.exe" set "RUNPY=%%~D\python.exe"
  )
)
if defined RUNPY (
  rem enterprise console wizard: choose SERVER or CLIENT role, LAN server
  rem discovery, arrow-key block selection; it then hands over to start.py
  %RUNPY% install_wizard.py
  if errorlevel 1 %RUNPY% start.py
  goto :done
)
echo ERROR: Python 3.12+ still not on PATH. Open a NEW terminal and run: py -3.12 start.py
echo (PATH changes need a fresh console on some systems.)
pause
exit /b 1

:done
echo.
echo Installation complete. The platform is running at http://127.0.0.1:8600
exit /b 0
