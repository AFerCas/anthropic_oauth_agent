# Adds (or with -Remove, deletes) a Startup-folder shortcut that runs start-agent.cmd at logon.
param([switch]$Remove)

$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'anthropic_oauth_agent.lnk'

if ($Remove) {
    if (Test-Path $link) { Remove-Item $link; "removed $link" } else { "not installed" }
    return
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $PSScriptRoot 'start-agent.cmd'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7  # minimized
$shortcut.Save()
"installed $link"
