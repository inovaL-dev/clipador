; Instalador do Clipador. O criar-exe.bat passa a versão e as pastas.
#ifndef Versao
  #define Versao "1.6.0"
#endif
#ifndef Origem
  #define Origem "..\build_exe\programa\Clipador"
#endif
#ifndef Destino
  #define Destino "..\instalador"
#endif

[Setup]
AppId={{7C1B6E52-3C0D-4C39-9A57-CF21A7D4E8B3}
AppName=Clipador
AppVersion={#Versao}
AppVerName=Clipador {#Versao}
AppPublisher=Clipador
VersionInfoVersion={#Versao}
VersionInfoDescription=Instalador do Clipador
DefaultDirName={userpf}\Clipador
DefaultGroupName=Clipador
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Destino}
OutputBaseFilename=Clipador-Instalador-{#Versao}
SetupIconFile=clipador.ico
UninstallDisplayIcon={app}\Clipador.exe
UninstallDisplayName=Clipador
WizardStyle=modern
WizardImageFile=instalador_lateral.bmp
WizardSmallImageFile=instalador_topo.bmp
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "atalho"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "segundo"; Description: "Continuar funcionando em segundo plano ao fechar a janela"; GroupDescription: "Segundo plano:"
Name: "iniciar"; Description: "Abrir junto com o Windows, em segundo plano"; GroupDescription: "Segundo plano:"; Flags: unchecked

[Files]
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Clipador"; Filename: "{app}\Clipador.exe"
Name: "{group}\Desinstalar o Clipador"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Clipador"; Filename: "{app}\Clipador.exe"; Tasks: atalho

[Registry]
Root: HKCU; Subkey: "Software\Clipador"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Clipador"; ValueType: dword; ValueName: "SegundoPlano"; ValueData: 1; Tasks: segundo
Root: HKCU; Subkey: "Software\Clipador"; ValueType: dword; ValueName: "SegundoPlano"; ValueData: 0; Tasks: not segundo
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "Clipador"; Flags: deletevalue uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Clipador"; ValueData: """{app}\Clipador.exe"" --segundo-plano"; Tasks: iniciar

[Run]
Filename: "{app}\Clipador.exe"; Description: "Abrir o Clipador agora"; Flags: nowait postinstall skipifsilent

[Code]
procedure FecharPrograma;
var
  Codigo: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Clipador.exe', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Sleep(800);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  FecharPrograma;
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  FecharPrograma;
  Result := True;
end;
