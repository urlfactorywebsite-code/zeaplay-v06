param([switch]$Apply)
$ErrorActionPreference = 'Stop'

function Invoke-Docker {
    param([string[]]$DockerArguments)
    $output = & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) { throw 'Docker command failed; no further initialization steps will run.' }
    return $output
}

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $root 'docker-compose.yml'
$postgres = 'zeaplay_v1-postgres-1'
$backend = 'zeaplay_v1-backend-1'
if ((Invoke-Docker @('context','show')).Trim() -ne 'desktop-linux') { throw 'Only the local Docker Desktop desktop-linux context is supported.' }
$labels = Invoke-Docker @('inspect',$postgres,'--format','{{json .Config.Labels}}') | ConvertFrom-Json
if ($labels.'com.docker.compose.project' -ne 'zeaplay_v1' -or
    [IO.Path]::GetFullPath($labels.'com.docker.compose.project.working_dir') -ne $root -or
    [IO.Path]::GetFullPath($labels.'com.docker.compose.project.config_files') -ne $composeFile) {
    throw 'The installed local database does not belong to this exact checkout.'
}
if ((Invoke-Docker @('inspect',$backend,'--format','{{.State.Running}}')).Trim() -ne 'false') {
    throw 'The backend must already be stopped before empty-database initialization.'
}
$count = Invoke-Docker @('exec',$postgres,'psql','-X','-U','zeaplay','-d','zeaplay','-A','-t','-v','ON_ERROR_STOP=1','-c',
    "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')")
if ($count.Trim() -ne '0') { throw 'Existing tables detected. Restore or review migrations instead; nothing was initialized.' }

if ($Apply) {
    # The operator explicitly chose fresh initialization with -Apply. Preserve
    # even this empty database before executing any DDL. Never delete a volume.
    $run = [guid]::NewGuid().ToString('N')
    $backupDirectory = Join-Path $env:TEMP ('zea-local-initialization-' + $run)
    New-Item -ItemType Directory -Path $backupDirectory | Out-Null
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $backupDirectory /inheritance:r /grant:r "*$($sid):(OI)(CI)F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict backup directory permissions.' }
    $containerBackup = '/tmp/zea-before-initialization-' + $run + '.dump'
    Invoke-Docker @('exec',$postgres,'pg_dump','-U','zeaplay','-d','zeaplay','-Fc','-f',$containerBackup) | Out-Null
    Invoke-Docker @('exec',$postgres,'pg_restore','--list',$containerBackup) | Out-Null
    $backupFile = Join-Path $backupDirectory 'before-initialization.dump'
    Invoke-Docker @('cp',($postgres + ':' + $containerBackup),$backupFile) | Out-Null
    Write-Output ('Validated pre-initialization backup: ' + $backupFile)
}

# Run current source read-only on the existing image; no backend rebuild or
# server startup is needed to inspect/apply the initializer. Credentials stay
# in the existing Compose environment and are never printed or copied here.
$backendSource = Join-Path $root 'backend'
$arguments = @('compose','-p','zeaplay_v1','-f',$composeFile,'run','--rm','--no-deps',
    '-v',($backendSource + ':/bootstrap:ro'),'-w','/tmp','-e','PYTHONPATH=/bootstrap',
    '-e','ZEA_ALEMBIC_MIGRATION=1','-e','ZEA_LOCAL_BOOTSTRAP_PROJECT=zeaplay_v1',
    '-e','ZEA_MCP_PHASE4A_ISOLATED=0','--entrypoint','python','backend',
    '-B','-m','checks.initialize_empty_local')
if ($Apply) { $arguments += '--apply' }
Invoke-Docker $arguments
if ($Apply) {
    Write-Output 'Initialization committed. MCP remains disabled; no Alembic version was stamped.'
    Write-Output 'Next: docker compose -p zeaplay_v1 up -d --no-deps --build backend'
} else {
    Write-Output 'Inspection only: database unchanged. For an intentional fresh local installation, rerun with -Apply.'
    Write-Output 'If previous users/tasks are expected, restore their backup instead.'
}
