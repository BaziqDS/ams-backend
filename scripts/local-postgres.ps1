param(
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
$postgresRoot = Join-Path $env:LOCALAPPDATA 'AMS'
$pgCtl = Join-Path $postgresRoot 'pgsql\bin\pg_ctl.exe'
$dataDirectory = Join-Path $postgresRoot 'data'
$logFile = Join-Path $postgresRoot 'postgresql.log'

if (-not (Test-Path -LiteralPath $pgCtl) -or -not (Test-Path -LiteralPath (Join-Path $dataDirectory 'PG_VERSION'))) {
    throw "The local AMS PostgreSQL installation was not found at $postgresRoot. See docs/local-development.md."
}

if ($Action -eq 'start') {
    & $pgCtl -D $dataDirectory status *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'AMS PostgreSQL is already running at 127.0.0.1:5432.'
        exit 0
    }
    $serverProcess = Start-Process -FilePath $pgCtl -WindowStyle Hidden -PassThru -ArgumentList @(
        '-D', ('"{0}"' -f $dataDirectory),
        '-l', ('"{0}"' -f $logFile), '-w', 'start'
    )
    $serverProcess.WaitForExit()
    if ($serverProcess.ExitCode -ne 0) {
        throw "PostgreSQL failed to start. Read $logFile."
    }
    Write-Host 'AMS PostgreSQL is running at 127.0.0.1:5432.'
    exit 0
} elseif ($Action -eq 'stop') {
    & $pgCtl -D $dataDirectory -m fast -w stop
    exit $LASTEXITCODE
} else {
    & $pgCtl -D $dataDirectory status
    exit $LASTEXITCODE
}
