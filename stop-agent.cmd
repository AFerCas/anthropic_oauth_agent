@echo off
rem Stop background agents started from this folder.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*anthropic_oauth_agent*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output ('stopped ' + $_.ProcessId) }"
