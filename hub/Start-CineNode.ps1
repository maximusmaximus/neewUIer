# CineNode Windows hub — double-click Start-CineNode.bat
# Uses native Windows Bluetooth. Do not run this inside WSL.
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$HubArgs
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Info([string]$Message) {
    Write-Host $Message
}

function Find-Python {
    $cmds = @(
        @{ File = "py"; Prefix = @("-3") },
        @{ File = "py"; Prefix = @() },
        @{ File = "python"; Prefix = @() },
        @{ File = "python3"; Prefix = @() }
    )
    foreach ($item in $cmds) {
        $cmd = Get-Command $item.File -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        try {
            $output = & $cmd.Source @($item.Prefix + @("--version")) 2>&1 | Out-String
            if ($output -match "Python 3") {
                return @{ Exe = $cmd.Source; Prefix = $item.Prefix }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Refresh-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

$python = Find-Python
if (-not $python) {
    Write-Info "Python 3 was not found."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "Installing Python 3.12 with winget (one-time)..."
        & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $python = Find-Python
    }
}

if (-not $python) {
    Write-Info "Install Python 3.10+ from https://www.python.org/downloads/windows/"
    Write-Info "During setup, check 'Add python.exe to PATH', then run this again."
    Write-Info "Do not use WSL — Windows Bluetooth is not visible there."
    exit 1
}

Write-Info "Installing bleak + paho-mqtt..."
& $python.Exe @($python.Prefix + @("-m", "pip", "install", "--user", "--upgrade", "bleak", "paho-mqtt"))
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not (Test-Path -Path "cinenode.json") -and (Test-Path -Path "cinenode.example.json")) {
    Copy-Item "cinenode.example.json" "cinenode.json"
    Write-Info "Wrote cinenode.json from the example — edit MQTT broker if needed."
}

Write-Info "Starting CineNode hub. Close the official Neewer app first."
Write-Info "Home Assistant color commands: topic cinenode/<light-id>/set"
& $python.Exe @($python.Prefix + @("cinenode-hub.py") + $HubArgs)
exit $LASTEXITCODE
