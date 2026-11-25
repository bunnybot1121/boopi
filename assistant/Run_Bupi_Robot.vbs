Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = strDir
WshShell.Run chr(34) & strDir & "\Run_Bupi_Robot.bat" & chr(34), 0, False
Set WshShell = Nothing
Set fso = Nothing
