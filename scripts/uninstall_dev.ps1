[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$KiCadVersions = @("9.0", "10.0"),
    [switch]$PurgeAppData
)

$ErrorActionPreference = "Stop"
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
    if ((Test-Path -LiteralPath $destination) -and
        $PSCmdlet.ShouldProcess($destination, "Uninstall JLCEDA2KICAD development plugin")) {
        Remove-Item -LiteralPath $destination -Recurse -Force
        Write-Host "Removed: $destination"
    }
}

if ($PurgeAppData) {
    $localRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA)
    $appData = [IO.Path]::GetFullPath((Join-Path $localRoot "HKRPT\JLCEDA2KICAD"))
    if (-not $appData.StartsWith($localRoot + [IO.Path]::DirectorySeparatorChar)) {
        throw "Refusing application data path outside LocalAppData: $appData"
    }
    if ((Test-Path -LiteralPath $appData) -and
        $PSCmdlet.ShouldProcess($appData, "Remove JLCEDA2KICAD settings, cache, and logs")) {
        Remove-Item -LiteralPath $appData -Recurse -Force
        Write-Host "Removed application data: $appData"
    }
}
