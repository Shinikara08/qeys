' One-click launcher for the Typing Overlay.
' Runs the app silently (no console window) and sends it to the system tray.
Set sh = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = scriptDir
sh.Run "pythonw """ & scriptDir & "\typing_overlay.py""", 0, False
