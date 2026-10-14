$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m PyInstaller --noconfirm --clean --onefile --windowed --name DeskMates --version-file assets/version-info.txt --icon assets/pet.ico --add-data "assets/spritesheet.png;assets" --add-data "assets/drag-landing-v3.png;assets" --add-data "assets/liberta-spritesheet.png;assets" --add-data "assets/liberta-motion.png;assets" --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick desktop_pet.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
