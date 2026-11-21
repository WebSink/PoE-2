# PoE 2 Control Center — PoB2/pob-mcp smoke check.
# Verifies local install paths and runs the real headless PoB2 engine
# through the pob-mcp Lua bridge. Read-only: does not modify the PoB install.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/check-pob.ps1

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$tools       = Join-Path $projectRoot ".tools"
$luajit      = Join-Path $tools "luajit\bin\luajit.exe"
$pob2        = Join-Path $tools "pob2"
$bridge      = Join-Path $tools "pob-mcp\lua\pob_bridge.lua"
$serverExe   = Join-Path $tools "pob-mcp\.venv\Scripts\pob-mcp.exe"

$failures = 0

function Check-Path([string]$label, [string]$path) {
    if (Test-Path -LiteralPath $path) {
        Write-Host "[ OK ] $label -> $path"
    } else {
        Write-Host "[FAIL] $label missing -> $path"
        $script:failures++
    }
}

Write-Host "== Paths =="
Check-Path "LuaJIT"        $luajit
Check-Path "PoB2 install"  (Join-Path $pob2 "Launch.lua")
Check-Path "PoB2 zlib"     (Join-Path $pob2 "zlib1.dll")
Check-Path "pob-mcp bridge" $bridge
Check-Path "pob-mcp server" $serverExe

if ($failures -gt 0) {
    Write-Host ""
    Write-Host "Smoke check FAILED: missing local components."
    exit 1
}

Write-Host ""
Write-Host "== LuaJIT =="
& $luajit -v

Write-Host ""
Write-Host "== Headless PoB2 bridge (new_build + get_stats) =="

$env:LUA_PATH  = "$pob2\lua\?.lua;$pob2\lua\?/init.lua;;"
$env:LUA_CPATH = "$pob2\?.dll;?"
$env:POB_MCP_ZLIB_PATH = Join-Path $pob2 "zlib1.dll"

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $luajit
$psi.Arguments = '"' + $bridge + '"'
$psi.WorkingDirectory = $pob2
$psi.UseShellExecute = $false
$psi.RedirectStandardInput = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

$proc = [System.Diagnostics.Process]::Start($psi)
$proc.StandardInput.WriteLine('{"id":1,"method":"new_build","params":{}}')
$proc.StandardInput.WriteLine('{"id":2,"method":"get_stats","params":{}}')
$proc.StandardInput.Close()

$stdout = $proc.StandardOutput.ReadToEnd()
$stderr = $proc.StandardError.ReadToEnd()
$proc.WaitForExit(120000) | Out-Null

if (-not $stdout.Contains('"ok":true')) {
    Write-Host "[FAIL] new_build did not return ok"
    Write-Host $stderr
    exit 1
}

if (-not $stdout.Contains('"stats"')) {
    Write-Host "[FAIL] get_stats did not return stats"
    Write-Host $stderr
    exit 1
}

Write-Host "[ OK ] bridge responded: new_build=ok, get_stats=stats"
Write-Host ""
Write-Host "Smoke check PASSED."
exit 0
