$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Failed to create build environment' }
& .venv/Scripts/python.exe -m pip install 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'Failed to install PyInstaller' }
& .venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --onefile --console --name HDU-Library-Seat-Windows-x64 --add-data "$PSScriptRoot/hdu_seat/web/index.html;hdu_seat/web" --specpath build windows_launcher.py
if ($LASTEXITCODE -ne 0) { throw 'Windows executable build failed' }
