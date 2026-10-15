@echo off
rem ============================================================
rem  Devre Analizi - gelistirme surumunu derleyip baslatir.
rem  Cift tiklamaniz yeterli. (Kurulum paketi hazir olunca bu
rem  dosyaya gerek kalmayacak.)
rem ============================================================
setlocal
cd /d "%~dp0"

rem .NET SDK kullanici klasorune kurulu (PATH'te olmayabilir)
set "PATH=%LOCALAPPDATA%\Microsoft\dotnet;%PATH%"

where dotnet >nul 2>nul
if errorlevel 1 (
    echo [HATA] .NET SDK bulunamadi. https://dotnet.microsoft.com/download adresinden .NET 8 SDK kurun.
    pause
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo [HATA] Python bulunamadi. Cozucu icin Python 3.10+ gerekli.
    pause
    exit /b 1
)

echo Derleniyor, lutfen bekleyin...
dotnet build CircuitAnalyzer.WPF\CircuitAnalyzer.WPF.csproj -nologo -v q -c Debug
if errorlevel 1 (
    echo.
    echo [HATA] Derleme basarisiz. Ayrintilar yukaridaki mesajlarda.
    pause
    exit /b 1
)

start "" "CircuitAnalyzer.WPF\bin\Debug\net8.0-windows\CircuitAnalyzer.exe"
endlocal
