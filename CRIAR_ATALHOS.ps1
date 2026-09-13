$ErrorActionPreference = "Stop"
$base = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $base "INICIAR.vbs"
$icon = Join-Path $base "ALT_Condominios.ico"
$name = "ALT Gestão de Condomínios"

if (-not (Test-Path $target)) { throw "INICIAR.vbs não encontrado." }
if (-not (Test-Path $icon)) { throw "Ícone da ALT não encontrado." }

$programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$desktop = [Environment]::GetFolderPath("Desktop")
New-Item -ItemType Directory -Force -Path $programs | Out-Null
$wsh = New-Object -ComObject WScript.Shell

foreach ($path in @(
    (Join-Path $programs "$name.lnk"),
    (Join-Path $desktop "$name.lnk")
)) {
    $s = $wsh.CreateShortcut($path)
    $s.TargetPath = "$env:SystemRoot\System32\wscript.exe"
    $s.Arguments = '"' + $target + '"'
    $s.WorkingDirectory = $base
    $s.IconLocation = "$icon,0"
    $s.Description = "Sistema de gestão de condomínios da ALT"
    $s.Save()
}
