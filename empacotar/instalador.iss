; Instalador do Clipador. O criar-exe.bat passa a versão e as pastas.
#ifndef Versao
  #define Versao "1.20.0"
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
AppMutex=ClipadorProgramaAberto
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

[InstallDelete]
Type: files; Name: "{app}\Clipador.antigo"

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
function ClipadorAberto(): Boolean;
var
  Codigo: Integer;
begin
  { tasklist lista o Clipador; o find devolve 0 quando acha o nome }
  Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq Clipador.exe" /NH | find /I "Clipador.exe" >nul', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Result := (Codigo = 0);
end;

procedure FecharPrograma;
var
  Codigo, Espera: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Clipador.exe', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  { o Windows leva um tempo para soltar os arquivos depois de fechar o programa }
  Espera := 0;
  while ClipadorAberto() and (Espera < 20) do
  begin
    Sleep(500);
    Espera := Espera + 1;
  end;
  Sleep(700);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Exe, Velho: String;
  Codigo: Integer;
begin
  Result := '';
  FecharPrograma;
  { aberto como administrador: o instalador não tem permissão para fechar, então pede para a pessoa }
  while ClipadorAberto() do
  begin
    if MsgBox('O Clipador ainda está aberto e o instalador não conseguiu fechar ele. Isso acontece quando o Clipador foi aberto como administrador.' + #13#10#13#10 +
              'Feche o Clipador: clique com o botão direito no ícone dele perto do relógio e escolha Sair. Se não achar, abra o Gerenciador de Tarefas (Ctrl+Shift+Esc), clique em Clipador e em Finalizar tarefa.' + #13#10#13#10 +
              'Depois clique em OK para continuar.', mbError, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := 'O Clipador continua aberto. Feche o Clipador e rode o instalador de novo.';
      Exit;
    end;
    FecharPrograma;
  end;
  { antivírus segurando o programa antigo: troca o nome dele para o novo poder entrar no lugar }
  Exe := ExpandConstant('{app}\Clipador.exe');
  Velho := ExpandConstant('{app}\Clipador.antigo');
  if FileExists(Exe) then
  begin
    { arquivo marcado como somente leitura também dá "Acesso negado" }
    Exec(ExpandConstant('{sys}\attrib.exe'), '-R -S -H "' + ExpandConstant('{app}') + '\*.*" /S', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
    DeleteFile(Velho);
    if not DeleteFile(Exe) then
      RenameFile(Exe, Velho);
  end;
end;

function InitializeUninstall(): Boolean;
begin
  FecharPrograma;
  Result := True;
end;
