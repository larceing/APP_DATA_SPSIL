Option Explicit

Dim shell, fso, projectDir, pidFile, pid, pidStream

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
pidFile = projectDir & "\server.pid"

If Not fso.FileExists(pidFile) Then
    MsgBox "No se encuentra server.pid: el servidor no parece estar en marcha.", vbExclamation, "Reporting"
    WScript.Quit
End If

Set pidStream = fso.OpenTextFile(pidFile, 1)
pid = Trim(pidStream.ReadLine())
pidStream.Close

' /T mata tambien los procesos hijos (daphne se lanzo bajo un cmd.exe)
shell.Run "taskkill /PID " & pid & " /T /F", 0, True

fso.DeleteFile(pidFile)

MsgBox "Servidor detenido (PID " & pid & ").", vbInformation, "Reporting"
