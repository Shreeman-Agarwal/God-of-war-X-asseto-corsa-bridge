[CmdletBinding()]
param(
    [string]$PythonExe = "py",
    [string[]]$SenderArguments = @()
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SenderPath = Join-Path $ProjectRoot "tools\assetto_corsa_sender.py"

if (-not (Test-Path -LiteralPath $SenderPath -PathType Leaf)) {
    Write-Error "Telemetry sender not found: $SenderPath"
}

$PythonCommand = Get-Command $PythonExe -ErrorAction SilentlyContinue
if ($null -eq $PythonCommand) {
    Write-Error "Python command '$PythonExe' was not found. Install Python 3.10+ or pass -PythonExe with its executable path."
}

Write-Host "GodWarBridge sender. Keep this window open; press Ctrl+C to stop."
Write-Host "Listening on localhost:47654. AC shared memory is retried while the game is closed."
Push-Location $ProjectRoot
try {
    if ($PythonExe -eq "py") {
        & $PythonCommand.Source -3 $SenderPath @SenderArguments
    } else {
        & $PythonCommand.Source $SenderPath @SenderArguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Telemetry sender exited with status $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
