Option Explicit

Dim shell, fso, scriptDir, projectDir

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)

If fso.FileExists(projectDir & "\server.pid") Then
    shell.Run "wscript.exe """ & scriptDir & "\stop_server.vbs""", 0, True
    WScript.Sleep 1500
End If

shell.Run "wscript.exe """ & scriptDir & "\start_server.vbs""", 0, True
