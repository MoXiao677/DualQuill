# Use the repository and installed runtimes; inspect is the default.
[CmdletBinding()]
param(
    [ValidateSet('Inspect', 'Validate')][string]$Mode = 'Inspect',
    [ValidateSet('upload', 'core', 'full')][string]$Checks = 'core',
    [string]$PythonPath,
    [string]$NodePath,
    [string]$ModulesPath,
    [string]$BrowserPath,
    [string]$ArtifactsPath
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskRuntime = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
if (-not $PythonPath) {
    $PythonPath = Join-Path $taskRuntime 'python\python.exe'
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw 'Python runtime missing; pass -PythonPath. No dependency installation was attempted.'
    }
}
if (-not $NodePath) {
    $NodePath = Join-Path $taskRuntime 'node\bin\node.exe'
    if (-not (Test-Path -LiteralPath $NodePath -PathType Leaf)) {
        $taskNode = Get-Command node -ErrorAction SilentlyContinue
        if ($taskNode) { $NodePath = $taskNode.Source }
    }
}
if (-not $ModulesPath) { $ModulesPath = Join-Path $taskRuntime 'node\node_modules' }
if (-not $BrowserPath) {
    $taskEdge = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'
    if (Test-Path -LiteralPath $taskEdge -PathType Leaf) { $BrowserPath = $taskEdge }
}
$taskArgs = @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'dev_workflow.py'),
              '--mode', $Mode.ToLowerInvariant(), '--checks', $Checks)
foreach ($taskOption in @(@('--node', $NodePath), @('--modules', $ModulesPath),
                          @('--browser', $BrowserPath), @('--artifacts', $ArtifactsPath))) {
    if ($taskOption[1]) { $taskArgs += $taskOption }
}
# Observe the current listener; never use a historical PID as a command target.
$taskListeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
if ($taskListeners.Count -eq 1) { $taskArgs += @('--service-pid', [string]$taskListeners[0].OwningProcess) }

# Quote argv using Windows CRT rules, including embedded quotes and trailing slashes.
function ConvertTo-DevProcessArgument([string]$Value) {
    $taskEscaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $taskEscaped = [regex]::Replace($taskEscaped, '(\\+)$', '$1$1')
    return '"' + $taskEscaped + '"'
}
$taskStart = New-Object System.Diagnostics.ProcessStartInfo
$taskStart.FileName = $PythonPath
$taskStart.Arguments = ($taskArgs | ForEach-Object { ConvertTo-DevProcessArgument ([string]$_) }) -join ' '
$taskStart.WorkingDirectory = $taskRoot
$taskStart.UseShellExecute = $false
$taskStart.CreateNoWindow = $true
$taskStart.RedirectStandardOutput = $true
$taskStart.RedirectStandardError = $true
$taskStart.StandardOutputEncoding = New-Object System.Text.UTF8Encoding $false
$taskStart.StandardErrorEncoding = New-Object System.Text.UTF8Encoding $false
$taskStart.EnvironmentVariables.Clear()
foreach ($taskName in @('PATH', 'SystemRoot', 'WINDIR', 'COMSPEC', 'USERPROFILE',
                        'LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'PATHEXT')) {
    $taskValue = [Environment]::GetEnvironmentVariable($taskName)
    if ($null -ne $taskValue) { $taskStart.EnvironmentVariables[$taskName] = $taskValue }
}
$taskProcess = New-Object System.Diagnostics.Process
$taskProcess.StartInfo = $taskStart
try {
    if (-not $taskProcess.Start()) { throw 'Failed to start the isolated development checker.' }
    $taskOutput = $taskProcess.StandardOutput.ReadToEndAsync()
    $taskErrorOutput = $taskProcess.StandardError.ReadToEndAsync()
    $taskProcess.WaitForExit()
    [Console]::Out.Write($taskOutput.GetAwaiter().GetResult())
    [Console]::Error.Write($taskErrorOutput.GetAwaiter().GetResult())
    $taskExitCode = $taskProcess.ExitCode
} finally {
    $taskProcess.Dispose()
}
exit $taskExitCode
