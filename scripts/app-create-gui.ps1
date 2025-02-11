
# To create the CLI and GUI apps for gitinspector,
# execute one of the following commands:
# pwsh scripts/pyinstall.zsh or scripts/pyinstall.ps1

# ROOTDIR is the root dir of the repo = the parent dir of the directory of this script
$ROOTDIR = Split-Path -Parent -Path (Split-Path -Parent -Path $MyInvocation.MyCommand.Definition)

# Make sure the gui conda environment is activated, so that pyinstaller can be found
# pwsh does not inherit the gui enviornment from the shell
conda activate gui

Write-Host "Deleting old app directories"
Remove-Item -Path "$ROOTDIR/app/*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$ROOTDIR/build" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Creating GUI bundle with gitinspectorgui"
Write-Host ""

pyinstaller --distpath="$ROOTDIR/app" "$ROOTDIR/app-gui-bundle.spec"
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Done, created gitinspectorgui.exe bundle in directory $ROOTDIR/app:"
}
