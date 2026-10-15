# ════════════════════════════════════════════════════════════════
#  Devre Analizi — kurulum paketini baştan üretir.
#
#    powershell -ExecutionPolicy Bypass -File installer\build.ps1 [-Version 1.0.0]
#
#  Gerekenler (yalnızca paketi HAZIRLAYAN bilgisayarda; kullanıcıda değil):
#    .NET 8 SDK, Python 3.10 + requirements.txt + pyinstaller, Inno Setup 6
#
#  Çıktı: build\installer\DevreAnalizi-Kurulum-<sürüm>.exe
# ════════════════════════════════════════════════════════════════

param(
    [string]$Version = "1.0.0"
)

# "Continue": PyInstaller bilgi mesajlarını stderr'e yazar; Windows PowerShell 5.1
# bunları hata sayıp betiği durdurmasın. Her adımın sonucu $LASTEXITCODE ile
# ya da -ErrorAction Stop ile ayrıca denetlenir.
$ErrorActionPreference = "Continue"
$Root  = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $Root "build"
$App   = Join-Path $Build "app"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

function Find-Tool($name, $candidates) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    throw "$name bulunamadı. Kurulu olduğundan emin olun."
}

$Dotnet = Find-Tool "dotnet" @("$env:LOCALAPPDATA\Microsoft\dotnet\dotnet.exe", "$env:ProgramFiles\dotnet\dotnet.exe")
$Python = Find-Tool "python" @()
$Iscc   = Find-Tool "ISCC" @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                             "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                             "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")
$DotnetRoot = Split-Path -Parent $Dotnet

Step "Eski çıktılar temizleniyor"
if (Test-Path $Build) { Remove-Item -Recurse -Force $Build -ErrorAction Stop }
New-Item -ItemType Directory -Force $App -ErrorAction Stop | Out-Null

Step "Python çözücüsü paketleniyor (PyInstaller)"
& $Python -m PyInstaller (Join-Path $PSScriptRoot "backend.spec") --noconfirm `
    --distpath (Join-Path $Build "dist") --workpath (Join-Path $Build "work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller başarısız" }

Step "WPF uygulaması yayımlanıyor (.NET kendi içinde)"
& $Dotnet publish (Join-Path $Root "CircuitAnalyzer.WPF\CircuitAnalyzer.WPF.csproj") `
    -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false `
    -p:Version=$Version -o $App -nologo
if ($LASTEXITCODE -ne 0) { throw "dotnet publish başarısız" }

Step "Çözücü uygulama klasörüne kopyalanıyor"
Copy-Item -Recurse (Join-Path $Build "dist\backend") (Join-Path $App "backend") -ErrorAction Stop

Step "Lisanslar toplanıyor"
& $Python (Join-Path $PSScriptRoot "collect_licenses.py") $App $DotnetRoot
if ($LASTEXITCODE -ne 0) { throw "Lisans toplama başarısız" }
Copy-Item (Join-Path $Root "LICENSE") (Join-Path $App "LICENSE.txt") -ErrorAction Stop
Copy-Item (Join-Path $Root "THIRD_PARTY_NOTICES.md") $App -ErrorAction Stop
Copy-Item (Join-Path $Root "licenses\LGPL-2.1.txt") (Join-Path $App "licenses") -ErrorAction Stop

Step "Çözücü deneniyor"
$port = 18765
$proc = Start-Process -FilePath (Join-Path $App "backend\CircuitAnalyzerAPI.exe") `
    -ArgumentList "--port", $port -PassThru -WindowStyle Hidden -ErrorAction Stop
try {
    $ok = $false
    for ($i = 0; $i -lt 120 -and -not $ok; $i++) {
        Start-Sleep -Milliseconds 250
        try { Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2 | Out-Null; $ok = $true } catch { }
    }
    if (-not $ok) { throw "Paketlenmiş çözücü 30 saniyede yanıt vermedi" }
    Write-Host "Çözücü yanıt veriyor."
} finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

Step "Kurulum dosyası derleniyor (Inno Setup)"
& $Iscc "/DAppVersion=$Version" "/DSourceDir=$App" (Join-Path $PSScriptRoot "DevreAnalizi.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup başarısız" }

$out = Join-Path $Build "installer\DevreAnalizi-Kurulum-$Version.exe"
$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "`nHazır: $out ($mb MB)" -ForegroundColor Green
