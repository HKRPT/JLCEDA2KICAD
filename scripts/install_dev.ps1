[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$KiCadVersions = @("9.0", "10.0")
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$identifier = "com.github.hkrpt.jlceda2kicad"

foreach ($version in $KiCadVersions) {
    if ($version -notmatch '^\d+\.\d+$') {
        throw "Invalid KiCad version directory: $version"
    }
    $pluginsRoot = [IO.Path]::GetFullPath((Join-Path $env:APPDATA "kicad\$version\plugins"))
    $destination = [IO.Path]::GetFullPath((Join-Path $pluginsRoot $identifier))
    if (-not $destination.StartsWith($pluginsRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing destination outside KiCad plugins directory: $destination"
    }
    if (-not $PSCmdlet.ShouldProcess($destination, "Install JLCEDA2KICAD development plugin")) {
        continue
    }
    if (Test-Path -LiteralPath $destination) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($file in @("plugin.json", "plugin_entry.py", "requirements.txt", "LICENSE", "README.md")) {
        Copy-Item -LiteralPath (Join-Path $repoRoot $file) -Destination $destination
    }
    Copy-Item -LiteralPath (Join-Path $repoRoot "resources") -Destination $destination -Recurse
    Copy-Item -LiteralPath (Join-Path $repoRoot "src\jlceda2kicad") -Destination $destination -Recurse
    Write-Host "Installed: $destination"
}

Write-Host "This script only copies plugin files. Install requirements with each KiCad Python runtime if needed."
