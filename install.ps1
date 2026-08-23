# Installs the ov CLI on Windows.
#
#   irm https://raw.githubusercontent.com/Just-Bax/ov-cli/master/install.ps1 | iex
#
# Nothing needs to be installed first. uv is fetched if missing and brings its
# own Python, so the machine never needs a system Python.

$ErrorActionPreference = 'Stop'

$Repo = 'Just-Bax/ov-cli'
$Branch = 'master'

function Write-Step($Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok($Message) { Write-Host "    $Message" -ForegroundColor Green }

function Add-LocalBinToPath {
    $LocalBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $LocalBin) {
        $env:Path = "$LocalBin;$env:Path"
    }
}

Write-Host ''
Write-Host 'ov - OneVizion from the command line' -ForegroundColor White
Write-Host ''

Add-LocalBinToPath

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Write-Step 'uv already installed'
} else {
    Write-Step 'Installing uv (provides Python, nothing else needed)'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    Add-LocalBinToPath
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv installed but is not on PATH. Close this window, open a new one, and re-run.'
}

Write-Step 'Installing ov'
# The zip avoids needing git on the machine.
$Source = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
uv tool install --force --python 3.12 "ov-cli @ $Source"
if ($LASTEXITCODE -ne 0) { throw 'Install failed.' }

uv tool update-shell 2>&1 | Out-Null
Add-LocalBinToPath

Write-Step 'Downloading the sign-in browser (about 150MB, one time)'
ov setup
if ($LASTEXITCODE -ne 0) { Write-Host '    Skipped. Run "ov setup" later.' -ForegroundColor Yellow }

Write-Host ''
Write-Ok 'Installed.'
Write-Host ''
Write-Host '  Open a NEW terminal, then run:' -ForegroundColor White
Write-Host '    ov login https://yours.onevizion.com'
Write-Host '    ov api tags'
Write-Host ''
