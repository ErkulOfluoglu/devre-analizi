; ════════════════════════════════════════════════════════════════
;  Devre Analizi — Inno Setup kurulum tarifi
;
;  Doğrudan derlemeyin; installer\build.ps1 önce uygulamayı ve
;  çözücüyü hazırlar, sonra bu dosyayı ISCC ile derler:
;    ISCC /DAppVersion=1.0.0 /DSourceDir=<hazırlanan klasör> DevreAnalizi.iss
;
;  Kurulum yönetici izni İSTEMEZ (okul bilgisayarları için):
;  varsayılan olarak yalnızca o kullanıcıya, %LOCALAPPDATA%\Programs
;  altına kurulur. İsteyen "tüm kullanıcılar" seçeneğini seçebilir.
; ════════════════════════════════════════════════════════════════

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\build\app"
#endif

#define AppName "Devre Analizi"
#define AppExe "CircuitAnalyzer.exe"
#define AppPublisher "Erkul Ofluoğlu"

[Setup]
; AppId kurulumu tanımlar; güncellemelerde AYNI kalmalı.
AppId={{134D9F30-2C77-4510-AB13-E4FF5202B230}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© 2026 {#AppPublisher} · MIT Lisansı
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=lisans.txt
SetupIconFile=..\CircuitAnalyzer.WPF\Assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=..\build\installer
OutputBaseFilename=DevreAnalizi-Kurulum-{#AppVersion}
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Ek seçenekler:"
Name: "assoc"; Description: ".devre dosyalarını Devre Analizi ile aç"; GroupDescription: "Ek seçenekler:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; .devre dosya ilişkilendirmesi (HKA = kuruluma göre HKCU veya HKLM)
Root: HKA; Subkey: "Software\Classes\.devre"; ValueType: string; ValueName: ""; ValueData: "DevreAnalizi.Devre"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.devre\OpenWithProgids"; ValueType: string; ValueName: "DevreAnalizi.Devre"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\DevreAnalizi.Devre"; ValueType: string; ValueName: ""; ValueData: "Devre Analizi devresi"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\DevreAnalizi.Devre\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\DevreAnalizi.Devre\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\{#AppExe}"; Description: "Devre Analizi'ni şimdi başlat"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Çözücünün çalışırken oluşturduğu önbellek dosyaları
Type: filesandordirs; Name: "{app}\backend\_internal\__pycache__"
