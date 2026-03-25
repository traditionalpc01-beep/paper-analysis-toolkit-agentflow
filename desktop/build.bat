@echo off
cd /d f:\paper-analysis-toolkit\desktop
echo Removing old release folder...
if exist release rmdir /s /q release
echo Building Electron app...
npm run build
echo Building NSIS installer...
node node_modules\electron-builder\lib\cli.js --win nsis
echo.
echo Checking output:
if exist release\*.exe (
    echo SUCCESS - Found installer:
    dir release\*.exe
) else (
    echo Checking win-unpacked:
    if exist release\win-unpacked\PaperInsight.exe (
        echo SUCCESS - Found executable in win-unpacked:
        dir release\win-unpacked\PaperInsight.exe
    ) else (
        echo FAIL - No exe found in release folder
    )
)
pause
