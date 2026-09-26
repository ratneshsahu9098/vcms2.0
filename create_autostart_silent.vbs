Set WshShell = WScript.CreateObject("WScript.Shell")
startupFolder = WshShell.SpecialFolders("Startup")
shortcutPath = startupFolder & "\VCMS_Silent.lnk"
targetPath = "F:\vcms_aug\venv\Scripts\pythonw.exe"
arguments = "F:\vcms_aug\run.py"
workingDir = "F:\vcms_aug"

Set shortcut = WshShell.CreateShortcut(shortcutPath)
shortcut.TargetPath = targetPath
shortcut.Arguments = arguments
shortcut.WorkingDirectory = workingDir
shortcut.WindowStyle = 0
shortcut.Description = "Auto-start VCMS server silently on Windows startup"
shortcut.Save

WScript.Echo "VCMS silent auto-start shortcut created in Startup folder."