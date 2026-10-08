@echo off
setlocal
cd /d "%~dp0"
if exist "dist\Label Fit.exe" (
    start "" "dist\Label Fit.exe" %*
    exit /b 0
)
where python >nul 2>nul
if errorlevel 1 (
    echo Python is required. Install Python 3.10 or newer from python.org.
    echo Enable "Add Python to PATH" during installation, then run this again.
    pause
    exit /b 1
)
python -c "import tkinter, pymupdf, PIL" >nul 2>nul
if not errorlevel 1 goto run
echo Installing the PDF and image libraries for Label Fit...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Setup failed. Check your internet connection and try again.
    pause
    exit /b 1
)
:run
python label_fit.py %*
if errorlevel 1 (
    echo Label Fit could not start. The error is shown above.
    pause
)
