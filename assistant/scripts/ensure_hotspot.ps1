# BUPI Windows Mobile Hotspot Auto-Enabler
# Ensures the Wi-Fi AP (CHINTU 4312) is active so ESP32 robots can connect automatically.

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    [Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType=WindowsRuntime] | Out-Null
    [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType=WindowsRuntime] | Out-Null

    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($null -eq $profile) {
        Write-Host "[Hotspot] No internet connection profile found. Cannot manage tethering."
        exit 0
    }

    $tm = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)
    if ($null -eq $tm) {
        Write-Host "[Hotspot] Could not create tethering manager."
        exit 0
    }

    $state = $tm.TetheringOperationalState
    if ($state -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::On) {
        $cfg = $tm.GetCurrentAccessPointConfiguration()
        Write-Host "[Hotspot] Mobile Hotspot is already ON: '$($cfg.Ssid)' ($($tm.ClientCount) robot(s) connected)."
        exit 0
    }

    Write-Host "[Hotspot] Mobile Hotspot is currently OFF. Starting Wi-Fi AP for robots..."
    $tm.StartTetheringAsync() | Out-Null

    # Wait up to 6 seconds for the hotspot to initialize
    $timeout = 0
    while ($tm.TetheringOperationalState -ne [Windows.Networking.NetworkOperators.TetheringOperationalState]::On -and $timeout -lt 12) {
        Start-Sleep -Milliseconds 500
        $timeout++
    }

    if ($tm.TetheringOperationalState -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::On) {
        $cfg = $tm.GetCurrentAccessPointConfiguration()
        Write-Host "[Hotspot] Mobile Hotspot started successfully: '$($cfg.Ssid)' (192.168.137.1)"
    } else {
        Write-Host "[Hotspot] Warning: Hotspot did not report ON within timeout (State: $($tm.TetheringOperationalState))"
    }
} catch {
    Write-Host "[Hotspot] Error verifying hotspot: $_"
}
exit 0
