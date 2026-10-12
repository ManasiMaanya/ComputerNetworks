# Run from anywhere:  .\scripts\run.ps1 p0   (if execution policy blocks .ps1, use scripts\*.cmd)
param(
    [Parameter(Position = 0)]
    [string] $Step = "p0",
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]] $Rest
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
$drive = $ProjectRoot.Substring(0, 1).ToLower()
$wslRoot = "/mnt/$drive" + ($ProjectRoot.Substring(2) -replace "\\", "/")

switch ($Step.ToLower()) {
    { $_ -in @("p0", "0", "load") } { python scripts/load_sample.py; exit $LASTEXITCODE }
    { $_ -in @("p1", "1", "features") } { python scripts/features.py --src R1 --dst R8 @Rest; exit $LASTEXITCODE }
    { $_ -in @("p2", "2", "baselines") } { python scripts/baselines.py --src R1 --dst R8 @Rest; exit $LASTEXITCODE }
    { $_ -in @("train", "p3") } { python scripts/train.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("infer", "p4", "explain") } { python scripts/infer.py --src R1 --dst R8 --explain @Rest; exit $LASTEXITCODE }
    { $_ -in @("compare", "p5") } { python scripts/compare.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("simulate", "p6") } { python scripts/simulate.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("traffic", "p6-traffic") } { python scripts/simulate.py --scenario configs/scenarios/traffic_dynamics.json @Rest; exit $LASTEXITCODE }
    { $_ -in @("zoo", "p7") } { python scripts/fetch_topology_zoo.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("mininet") } { python scripts/export_mininet.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("pt", "packet-tracer") } { python scripts/packet_tracer.py export @Rest; exit $LASTEXITCODE }
    { $_ -in @("demo", "all") } { python scripts/demo.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("test", "tests") } { python scripts/run_tests.py @Rest; exit $LASTEXITCODE }
    { $_ -in @("web-up", "webup") } {
        wsl -e bash -lc "cd '$wslRoot' && chmod +x scripts/*.sh && ./scripts/wsl-web-up.sh"
        exit $LASTEXITCODE
    }
    { $_ -in @("web-down", "webdown") } {
        wsl -e bash -lc "cd '$wslRoot' && ./scripts/wsl-web-down.sh"
        exit $LASTEXITCODE
    }
    { $_ -in @("web-test", "webtest") } { python scripts/web_health.py; exit $LASTEXITCODE }
    { $_ -in @("web", "web-local") } { python -m uvicorn web.app:app --host 127.0.0.1 --port 8765; exit $LASTEXITCODE }
    default {
        Write-Error "Unknown step '$Step'. Use p0, p1, p2, train, infer, compare, simulate, traffic, zoo, mininet, pt, demo, tests, web, web-up, web-down, web-test."
        exit 1
    }
}
