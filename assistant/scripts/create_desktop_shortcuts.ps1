$desktopPaths = @(
    [Environment]::GetFolderPath('Desktop'),
    'C:\Users\Sachin\Desktop'
) | Select-Object -Unique

$WshShell = New-Object -ComObject WScript.Shell

foreach ($dp in $desktopPaths) {
    if (Test-Path $dp) {
        # 1. Daily Git Sync Shortcut
        $s1 = $WshShell.CreateShortcut((Join-Path $dp "BUPI Daily Git Sync.lnk"))
        $s1.TargetPath = 'C:\Users\Sachin\boopi\assistant\scripts\daily_git_sync.bat'
        $s1.WorkingDirectory = 'C:\Users\Sachin\boopi\assistant'
        $s1.IconLocation = 'cmd.exe,0'
        $s1.Description = 'BUPI Automated Daily DevLog & Git Push to GitHub'
        $s1.Save()
        Write-Host "Created: $(Join-Path $dp 'BUPI Daily Git Sync.lnk')"

        # 2. Sonar Vision Server Shortcut
        $s2 = $WshShell.CreateShortcut((Join-Path $dp "BUPI Sonar Vision Server.lnk"))
        $s2.TargetPath = 'C:\Users\Sachin\boopi\assistant\scripts\run_sonar_server.bat'
        $s2.WorkingDirectory = 'C:\Users\Sachin\boopi\assistant'
        $s2.IconLocation = 'shell32.dll,14'
        $s2.Description = 'Start BUPI Sonar Vision 2.5D/3D Server (http://localhost:8050)'
        $s2.Save()
        Write-Host "Created: $(Join-Path $dp 'BUPI Sonar Vision Server.lnk')"
    }
}
