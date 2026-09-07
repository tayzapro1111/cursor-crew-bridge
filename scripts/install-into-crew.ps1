#Requires -Version 5.1
# Kept for older notes. Same as setup.ps1 in the repo root.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
& (Join-Path $Root "setup.ps1")
