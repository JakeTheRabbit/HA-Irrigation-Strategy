$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath '.').Path
$taskArchive = Join-Path $taskRoot 'archive\2026-09-08'
if (Test-Path -LiteralPath $taskArchive) { throw 'Archive destination already exists; inspect before continuing.' }
$taskSources = @(
 'www\f2-classic.html','www\home.html','www\overview.html','www\setpoints.html',
 'www\crop_steering.html','www\crop_steering_tune.html','www\crop_steering_rules.html',
 'www\office.html','www\system-map.html','www\irrigation-manual.html','www\install.html',
 'www\SYSTEM_GUIDE.html','www\dashboard-nav.js','www\floorplan',
 'SYSTEM_GUIDE.html','SYSTEM_GUIDE.md','ENV_CONFIGURATION_GUIDE.md',
 'scripts\capture_demo_shots.js','scripts\capture_shots.py','scripts\check_tips_coverage.js',
 'scripts\verify_home.js','scripts\verify_overlay.py','scripts\render_guide.py','scripts\tips_data.json',
 'docs\HOME_ASSISTANT_FORUM_POST.md','docs\FEATURES_AND_TODO.md','docs\DASHBOARDS.md',
 'docs\AUTONOMOUS_SETPOINTS.md'
)
$taskMoves = foreach ($taskRelative in $taskSources) {
 $taskSource = (Resolve-Path -LiteralPath (Join-Path $taskRoot $taskRelative)).Path
 $taskDestination = [System.IO.Path]::GetFullPath((Join-Path $taskArchive $taskRelative))
 if (-not $taskSource.StartsWith($taskRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw "Source escaped workspace: $taskRelative" }
 if (-not $taskDestination.StartsWith($taskRoot + '\archive\', [System.StringComparison]::OrdinalIgnoreCase)) { throw "Destination escaped archive: $taskRelative" }
 [PSCustomObject]@{ Relative = $taskRelative; Source = $taskSource; Destination = $taskDestination }
}
$taskManifest = foreach ($taskMove in $taskMoves) {
 $taskFiles = if ((Get-Item -LiteralPath $taskMove.Source).PSIsContainer) { Get-ChildItem -LiteralPath $taskMove.Source -Recurse -File } else { Get-Item -LiteralPath $taskMove.Source }
 foreach ($taskFile in $taskFiles) {
  [PSCustomObject]@{ source = $taskFile.FullName.Substring($taskRoot.Length + 1); sha256 = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash; bytes = $taskFile.Length }
 }
}
New-Item -ItemType Directory -Path $taskArchive | Out-Null
$taskManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $taskArchive 'manifest.json') -Encoding utf8
foreach ($taskMove in $taskMoves) {
 New-Item -ItemType Directory -Path (Split-Path -Parent $taskMove.Destination) -Force | Out-Null
 Move-Item -LiteralPath $taskMove.Source -Destination $taskMove.Destination
}
Copy-Item -LiteralPath (Join-Path $taskRoot 'README.md') -Destination (Join-Path $taskArchive 'README-previous.md')
'Archived {0} explicit source paths; manifest records {1} files.' -f $taskMoves.Count,$taskManifest.Count
