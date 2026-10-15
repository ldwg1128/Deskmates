param([string]$OutputDirectory = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DeskMates --distpath $OutputDirectory --version-file assets/version-info.txt --icon assets/pet.ico --add-data "assets;assets" --add-data "characters;characters" --add-data "animation_catalog.json;." --exclude-module PIL --exclude-module numpy --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick desktop_pet.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
