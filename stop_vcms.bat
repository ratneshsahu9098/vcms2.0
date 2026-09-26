@echo off
echo Stopping VCMS server...
taskkill /F /FI "WINDOWTITLE eq *run.py*" /FI "IMAGENAME eq python.exe" >nul 2>&1
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *run.py*" >nul 2>&1
taskkill /F /IM python.exe /FI "COMMANDLINE eq *run.py*" >nul 2>&1

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo VCMS server stopped.
pause