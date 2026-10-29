$projectFolder = $PSScriptRoot
$allProcesses = @(Get-CimInstance Win32_Process)
$processes = @($allProcesses | Where-Object { $_.ExecutablePath -like "$projectFolder\*" -and ($_.Name -eq 'llama-server.exe' -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'app\.py')) })
# Python venv launchers can delegate to the base interpreter outside this folder.
$childProcesses = @($allProcesses | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'app\.py' -and $_.ParentProcessId -in $processes.ProcessId })
foreach ($taskProcess in ($childProcesses + $processes)) { Stop-Process -Id $taskProcess.ProcessId -ErrorAction SilentlyContinue }
