Option Explicit

Dim shell, fso, projectDir, pidFile, logFile, cmd, exec

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pidFile = projectDir & "\server.pid"
logFile = projectDir & "\logs\server.log"

If fso.FileExists(pidFile) Then
    MsgBox "El servidor ya parece estar en marcha (existe server.pid)." & vbCrLf & _
           "Usa restart_server.vbs si quieres reiniciarlo, o borra server.pid si quedo huerfano.", _
           vbExclamation, "Reporting"
    WScript.Quit
End If

cmd = "cmd /c cd /d """ & projectDir & """ && venv\Scripts\daphne.exe -b 0.0.0.0 -p 8000 config.asgi:application >> """ & logFile & """ 2>&1"
Set exec = shell.Exec(cmd)

Dim pidStream
Set pidStream = fso.CreateTextFile(pidFile, True)
pidStream.WriteLine exec.ProcessID
pidStream.Close

MsgBox "Servidor iniciado en http://localhost:8000 (PID " & exec.ProcessID & ")." & vbCrLf & _
       "Log: logs\server.log", vbInformation, "Reporting"
