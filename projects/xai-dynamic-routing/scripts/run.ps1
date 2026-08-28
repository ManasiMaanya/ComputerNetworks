# Run from anywhere:  .\scripts\run.ps1 p0
param(
    [Parameter(Position = 0)]
    [string] $Step = "p0"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$drive = $ProjectRoot.Substring(0, 1).ToLower()
$wslRoot = "/mnt/$drive" + ($ProjectRoot.Substring(2) -replace "\\", "/")

switch ($Step.ToLower()) {
    { $_ -in @("p0", "0", "load") } {
        python scripts/load_sample.py
        exit $LASTEXITCODE
    }
    { $_ -in @("p1", "1") } {
        Write-Error "Phase 1 script not added yet. See docs/execution-plan.md."
        exit 1
    }
    { $_ -in @("train") } {
        python scripts/train.py
        exit $LASTEXITCODE
    }
    { $_ -in @("infer") } {
        python scripts/infer.py
        exit $LASTEXITCODE
    }
    { $_ -in @("compare") } {
        python scripts/compare.py
        exit $LASTEXITCODE
    }
    { $_ -in @("web-up", "webup") } {
        wsl -e bash -lc "cd '$wslRoot' && chmod +x scripts/*.sh && ./scripts/wsl-web-up.sh"
        exit $LASTEXITCODE
    }
    { $_ -in @("web-down", "webdown") } {
        wsl -e bash -lc "cd '$wslRoot' && ./scripts/wsl-web-down.sh"
        exit $LASTEXITCODE
    }
    { $_ -in @("web-test", "webtest") } {
        python scripts/web_health.py
        exit $LASTEXITCODE
    }
    default {
        Write-Error "Unknown step '$Step'. Use p0, web-up, web-down, web-test. Later: p1, train, infer, compare."
        exit 1
    }
}
