[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$KiCadVersions = @("9.0", "10.0"),
    [string]$VendorDir = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$identifier = "io.hkrpt.jlc"
$documentsRoot = [Environment]::GetFolderPath("MyDocuments")
if ([string]::IsNullOrWhiteSpace($VendorDir)) {
    $VendorDir = Join-Path $repoRoot ".offline-build\vendor"
}
$vendorSource = [IO.Path]::GetFullPath($VendorDir)

foreach ($version in $KiCadVersions) {
    if ($version -notmatch '^\d+\.\d+$') {
        throw "Invalid KiCad version directory: $version"
    }
    $pluginsRoot = [IO.Path]::GetFullPath((Join-Path $documentsRoot "KiCad\$version\plugins"))
    $destination = [IO.Path]::GetFullPath((Join-Path $pluginsRoot $identifier))
    if (-not $destination.StartsWith($pluginsRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing destination outside KiCad plugins directory: $destination"
    }
    if (-not $PSCmdlet.ShouldProcess($destination, "Install JLCEDA2KICAD development plugin")) {
        continue
    }
    if (-not (Test-Path -LiteralPath $vendorSource -PathType Container)) {
        throw "Bundled runtime is missing: $vendorSource. Run scripts/offline_vendor.py first."
    }
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    foreach ($file in @(
        "plugin.json",
        "plugin_entry.py",
        "plugin_bootstrap.py",
        "requirements.txt",
        "LICENSE",
        "README.md"
    )) {
        Copy-Item -LiteralPath (Join-Path $repoRoot $file) -Destination $destination -Force
    }
    $resourcesDestination = Join-Path $destination "resources"
    $packageDestination = Join-Path $destination "jlceda2kicad"
    $vendorDestination = Join-Path $destination "vendor"
    New-Item -ItemType Directory `
        -Path $resourcesDestination, $packageDestination, $vendorDestination `
        -Force | Out-Null
    Copy-Item -Path (Join-Path $repoRoot "resources\*") `
        -Destination $resourcesDestination -Recurse -Force
    Copy-Item -Path (Join-Path $repoRoot "src\jlceda2kicad\*.py") `
        -Destination $packageDestination -Force
    Copy-Item -Path (Join-Path $vendorSource "*") `
        -Destination $vendorDestination -Recurse -Force
    Write-Host "Installed: $destination"
}

Write-Host "Runtime dependencies are bundled. Restart PCB Editor and refresh plugins."
