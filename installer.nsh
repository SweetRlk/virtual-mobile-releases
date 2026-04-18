; Copy telemetry DLL after installation
!macro customInstall
  MessageBox MB_YESNO "Deseja instalar o plugin de telemetria do ETS2?$\r$\n$\r$\nNecessário para o Virtual Mobile funcionar." IDYES choosePath IDNO skipTelemetry

  choosePath:
    nsDialogs::SelectFolderDialog "Selecione a pasta RAIZ do Euro Truck Simulator 2$\r$\n(Ex: C:\Program Files (x86)\Steam\steamapps\common\Euro Truck Simulator 2)" "C:\Program Files (x86)\Steam\steamapps\common\Euro Truck Simulator 2"
    Pop $0
    StrCmp $0 "error" skipTelemetry
    StrCmp $0 "" skipTelemetry

    CreateDirectory "$0\bin\win_x64\plugins"
    CopyFiles /SILENT "$INSTDIR\resources\scs-telemetry.dll" "$0\bin\win_x64\plugins\scs-telemetry.dll"
    MessageBox MB_OK "Plugin instalado em:$\r$\n$0\bin\win_x64\plugins"
    Goto doneTelemetry

  skipTelemetry:

  doneTelemetry:
!macroend
