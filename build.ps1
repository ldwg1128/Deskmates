param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimeCharacters = Join-Path $PSScriptRoot ('build/runtime-characters-' + [Guid]::NewGuid().ToString('N'))
python tools/stage_runtime_characters.py --output $runtimeCharacters
if ($LASTEXITCODE -ne 0) { throw 'Character packaging failed' }
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DeskMates --distpath $OutputDirectory --version-file assets/version-info.txt --icon assets/pet.ico --add-data "assets;assets" --add-data "${runtimeCharacters};characters" --add-data "animation_catalog.json;." --exclude-module PIL --exclude-module numpy --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick desktop_pet.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
