# Run from anywhere:  .\scripts\run.ps1 p0
param(
    [Parameter(Position = 0)]
    [string] $Step = "p0"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

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
    default {
        Write-Error "Unknown step '$Step'. Use p0 (ready). Later: p1, train, infer, compare."
        exit 1
    }
}
