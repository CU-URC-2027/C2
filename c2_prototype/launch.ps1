Set-Location -LiteralPath $PSScriptRoot
$c2BundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$c2VenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$c2AnacondaPython = Join-Path $env:USERPROFILE 'Anaconda\python.exe'
if (Test-Path -LiteralPath $c2VenvPython) {
    & $c2VenvPython app.py @args
} elseif (Test-Path -LiteralPath $c2AnacondaPython) {
    & $c2AnacondaPython app.py @args
} elseif (Test-Path -LiteralPath $c2BundledPython) {
    & $c2BundledPython app.py @args
} else {
    python app.py @args
}
