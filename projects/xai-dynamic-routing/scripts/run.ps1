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
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) {
            docker compose up --build -d
            exit $LASTEXITCODE
        }
        Write-Host "Docker not on PATH. Starting local uvicorn. Ctrl+C to stop."
        python -m uvicorn web.app:app --host 127.0.0.1 --port 8765
        exit $LASTEXITCODE
    }
    { $_ -in @("web-down", "webdown") } {
        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) {
            docker compose down
            exit $LASTEXITCODE
        }
        Write-Host "No Docker CLI. Stop uvicorn with Ctrl+C in the start window."
        exit 0
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
