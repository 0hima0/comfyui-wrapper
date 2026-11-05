param(
    [ValidateSet('all','python','frontend')][string]$Suite='all',
    [switch]$NoBuild
)
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$image='comfyui-wrapper-tests:local'
if(-not(Get-Command docker -ErrorAction SilentlyContinue)){
    throw 'Dockerが見つかりません。Docker Desktopを導入し、Linuxコンテナを起動してください。'
}
Push-Location $projectRoot
try{
    if(-not $NoBuild){
        & docker build --file docker/tests/Dockerfile --tag $image .
        if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}
    }
    $testArgs=@()
    if($Suite -eq 'python'){$testArgs+='--python-only'}
    if($Suite -eq 'frontend'){$testArgs+='--frontend-only'}
    & docker run --rm --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=1g,mode=1777 --cap-drop ALL --security-opt no-new-privileges $image @testArgs
    $testExitCode=$LASTEXITCODE
}finally{
    Pop-Location
}
exit $testExitCode