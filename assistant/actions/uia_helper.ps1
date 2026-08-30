param(
    [string]$Action,
    [string]$App,
    [string]$Label,
    [string]$Value
)

# Load assemblies
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

# Find the process
$proc = Get-Process -Name $App -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) {
    # Try finding process by MainWindowTitle matching App
    $proc = [System.Diagnostics.Process]::GetProcesses() | Where-Object { $_.MainWindowTitle -like "*$App*" } | Select-Object -First 1
}

if (-not $proc) {
    Write-Error "Application '$App' not found."
    exit 1
}

$hwnd = $proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero -or $hwnd -eq 0) {
    # If main window handle is zero, try to find windows owned by process
    $windows = [System.Diagnostics.Process]::GetProcesses() | Where-Object { $_.Name -eq $App -or $_.ProcessName -eq $App }
    foreach ($w in $windows) {
        if ($w.MainWindowHandle -ne 0) {
            $hwnd = $w.MainWindowHandle
            break
        }
    }
}

if ($hwnd -eq 0 -or $hwnd -eq [IntPtr]::Zero) {
    Write-Error "MainWindowHandle is zero for process '$App'."
    exit 1
}

# Get UIA element
$ae = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)
if (-not $ae) {
    Write-Error "Failed to get AutomationElement from window handle."
    exit 1
}

if ($Action -eq "list") {
    $elements = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $results = @()
    foreach ($el in $elements) {
        $name = $el.Current.Name
        $controlType = $el.Current.ControlType.ProgrammaticName.Split('.')[-1]
        if ($name) {
            # Only list interactive control types to keep output clean and avoid budget limit
            if ($controlType -in @("Button", "ListItem", "Edit", "Text", "MenuItem", "CheckBox", "RadioButton", "Hyperlink", "Document", "ComboBox")) {
                $results += "$controlType|$name"
            }
        }
    }
    # Deduplicate and print
    $results | Select-Object -Unique | Write-Output
}
elseif ($Action -eq "press") {
    # Search for element matching Label
    $elements = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $target = $null
    
    # Try exact match first
    foreach ($el in $elements) {
        if ($el.Current.Name -eq $Label) {
            $target = $el
            break
        }
    }
    
    # Try substring match if exact not found
    if (-not $target) {
        foreach ($el in $elements) {
            if ($el.Current.Name -like "*$Label*") {
                $target = $el
                break
            }
        }
    }
    
    if (-not $target) {
        Write-Error "Element with label '$Label' not found in '$App'."
        exit 1
    }
    
    $controlType = $target.Current.ControlType.ProgrammaticName.Split('.')[-1]
    
    # Attempt InvokePattern
    $invokePatternObj = $null
    if ($target.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invokePatternObj)) {
        $invokePatternObj.Invoke()
        Write-Output "Invoked element '$Label' ($controlType)."
        exit 0
    }
    
    # Attempt SelectionItemPattern
    $selectPatternObj = $null
    if ($target.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$selectPatternObj)) {
        $selectPatternObj.Select()
        Write-Output "Selected element '$Label' ($controlType)."
        exit 0
    }
    
    # Attempt TogglePattern
    $togglePatternObj = $null
    if ($target.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$togglePatternObj)) {
        $togglePatternObj.Toggle()
        Write-Output "Toggled element '$Label' ($controlType)."
        exit 0
    }
    
    # Fallback: Return coordinates
    try {
        $point = $target.GetClickablePoint()
        Write-Output "Coordinates|$($point.X)|$($point.Y)"
        exit 0
    }
    catch {
        Write-Error "No patterns or clickable point found for element '$Label' ($controlType)."
        exit 1
    }
}
elseif ($Action -eq "set_value") {
    # Search for element matching Label
    $elements = $ae.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    $target = $null
    
    foreach ($el in $elements) {
        if ($el.Current.Name -eq $Label -and ($el.Current.ControlType.ProgrammaticName.EndsWith("Edit") -or $el.Current.ControlType.ProgrammaticName.EndsWith("Document") -or $el.Current.ControlType.ProgrammaticName.EndsWith("ComboBox"))) {
            $target = $el
            break
        }
    }
    
    if (-not $target) {
        # Fallback to name match only if no type match
        foreach ($el in $elements) {
            if ($el.Current.Name -like "*$Label*") {
                $target = $el
                break
            }
        }
    }
    
    if (-not $target) {
        Write-Error "Text input element with label '$Label' not found in '$App'."
        exit 1
    }
    
    $valuePatternObj = $null
    if ($target.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$valuePatternObj)) {
        $valuePatternObj.SetValue($Value)
        Write-Output "Set element '$Label' value to '$Value'."
        exit 0
    }
    else {
        # Try focus and key send if ValuePattern is not supported
        $target.SetFocus()
        Write-Output "SendKeys|$Value"
        exit 0
    }
}
