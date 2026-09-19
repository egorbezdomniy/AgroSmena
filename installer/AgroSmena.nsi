Unicode true
!include "MUI2.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!ifndef APP_VERSION
!define APP_VERSION "0.1.0"
!endif
!ifndef PRODUCT_VERSION
!define PRODUCT_VERSION "0.1.0.0"
!endif

Name "АгроСмена CRM"
OutFile "..\dist\AgroSmenaCRM-${APP_VERSION}-Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\AgroSmenaCRM"
InstallDirRegKey HKCU "Software\AgroSmenaCRM" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "АгроСмена CRM ${APP_VERSION}"
Icon "..\build\crm.ico"
UninstallIcon "..\build\crm.ico"
VIProductVersion "${PRODUCT_VERSION}"
VIAddVersionKey "ProductName" "АгроСмена CRM"
VIAddVersionKey "FileDescription" "Установщик АгроСмена CRM"
VIAddVersionKey "FileVersion" "${APP_VERSION}"
VIAddVersionKey "LegalCopyright" "АгроСмена CRM"

!define MUI_ABORTWARNING
!define MUI_ICON "..\build\crm.ico"
!define MUI_UNICON "..\build\crm.ico"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Russian"

Function .onInit
    ${IfNot} ${AtLeastWin10}
        MessageBox MB_OK|MB_ICONSTOP "Необходима Windows 10 или новее."
        Abort
    ${EndIf}
    ${IfNot} ${RunningX64}
        MessageBox MB_OK|MB_ICONSTOP "Необходима 64-разрядная Windows."
        Abort
    ${EndIf}
    SetShellVarContext current
FunctionEnd

Section "Приложение"
    SetOutPath "$INSTDIR"
    File /r "..\dist\AgroSmenaCRM\*.*"
    WriteUninstaller "$INSTDIR\Uninstall.exe"
    CreateDirectory "$SMPROGRAMS\АгроСмена CRM"
    CreateShortcut "$SMPROGRAMS\АгроСмена CRM\АгроСмена CRM.lnk" "$INSTDIR\AgroSmenaCRM.exe"
    CreateShortcut "$DESKTOP\АгроСмена CRM.lnk" "$INSTDIR\AgroSmenaCRM.exe"
    WriteRegStr HKCU "Software\AgroSmenaCRM" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "DisplayName" "АгроСмена CRM"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "DisplayIcon" "$INSTDIR\AgroSmenaCRM.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM" "NoRepair" 1
SectionEnd

Section "Uninstall"
    SetShellVarContext current
    Delete "$DESKTOP\АгроСмена CRM.lnk"
    Delete "$SMPROGRAMS\АгроСмена CRM\АгроСмена CRM.lnk"
    RMDir "$SMPROGRAMS\АгроСмена CRM"
    ; Only remove known application files, never the user database directory.
    Delete "$INSTDIR\AgroSmenaCRM.exe"
    Delete "$INSTDIR\updater.exe"
    Delete "$INSTDIR\version.json"
    RMDir /r "$INSTDIR\_internal"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgroSmenaCRM"
    DeleteRegKey HKCU "Software\AgroSmenaCRM"
SectionEnd
