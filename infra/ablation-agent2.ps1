# 消融评测 E2/E3/E4（agent 侧）
#
# 三个实验都靠**服务启动时的环境变量**切换条件，所以每次测量前重启 agent。
#
#   E3 闸门：把阈值调到 1，跑 3 次，看工具调用次数与 token
#   E2 压缩：30 轮对话，看 token 增长 + 最后考一次约束
#   E4 故障：把后端地址指向死端口，看重试与降级
#
# 之所以 E3 要把阈值调到 1：阈值 2 时模型根本不会触发（它只搜 2 次就停），
# 实验会变成"两个条件完全一样"。调到 1 才能观察到闸门的真实行为。

param(
    [string]$LogDir = 'D:\Develop\AI\deepseek\test2\infra',
    [string]$Python = 'D:\Develop\AI\deepseek\test2\agent\.venv\Scripts\python.exe',
    [string]$AgentDir = 'D:\Develop\AI\deepseek\test2\agent',
    [int]$Turns = 30,
    [int]$GateRuns = 3,
    [switch]$SkipE2
)

$ErrorActionPreference = 'Stop'
$BaseEnv = @{}

function Get-ApiKey {
        # 凭据路径不写死：优先环境变量，其次用户目录（不泄露本机用户名）
    $credPath = if ($env:DSH_CREDENTIALS) {
        $env:DSH_CREDENTIALS
    } else {
        Join-Path $env:USERPROFILE '.dsh\.credentials.yaml'
    }
    if (-not (Test-Path $credPath)) { throw "找不到凭据文件：$credPath（可用 DSH_CREDENTIALS 指定）" }
    $cred = Get-Content $credPath -Raw
    $m = [regex]::Match($cred, 'DEEPSEEK_API_KEY:\s*"?([^"\r\n]+)"?')
    if (-not $m.Success) { throw '未找到 DEEPSEEK_API_KEY' }
    return $m.Groups[1].Value.Trim()
}

function Stop-Agent {
    # 只杀"监听端口"的那个进程不够：uvicorn 可能有父子两个，
    # 父进程不监听但活着，端口就释放不掉，下一次启动会 bind 失败。
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*uvicorn*app.main*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # 等端口真正释放（最多 25 秒）
    for ($i = 0; $i -lt 25; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw '8090 端口 25 秒内未释放'
}

function Start-Agent([hashtable]$extraEnv) {
    $envs = @{
        AGENT_SERVICE_TOKEN  = 'demo-agent-token-local'
        BACKEND_BASE_URL     = 'http://localhost:8081'
        DEEPSEEK_API_KEY     = (Get-ApiKey)
        CONTEXT_TOKEN_BUDGET = '1500'
    }
    foreach ($k in $extraEnv.Keys) { $envs[$k] = $extraEnv[$k] }

    # 用进程级环境变量 + Start-Process：子进程会继承，且能把日志落到文件，
    # 启动失败时可以直接看 _agent_err.log。
    foreach ($k in $envs.Keys) { Set-Item -Path ("env:" + $k) -Value ([string]$envs[$k]) }
    $outLog = Join-Path $LogDir '_agent_out.log'
    $errLog = Join-Path $LogDir '_agent_err.log'
    Start-Process -FilePath $Python `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8090' `
        -WorkingDirectory $AgentDir -WindowStyle Hidden `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest 'http://127.0.0.1:8090/health' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { Start-Sleep -Seconds 2; return }
        } catch { }
    }
    "--- agent stderr 末尾 ---"
    Get-Content $errLog -Tail 20 -ErrorAction SilentlyContinue
    throw 'agent 120 秒内未就绪'
}

function Invoke-Measure([string]$scenario, [string]$tag, [int]$turns = 0) {
    $out = Join-Path $LogDir ("_abl2_{0}_{1}.json" -f $scenario, $tag)
    $log = Join-Path $LogDir ("_abl2_{0}_{1}.log" -f $scenario, $tag)
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $args = @((Join-Path (Join-Path $AgentDir 'scripts') 'measure_ablation.py'), '--scenario', $scenario, '--out', $out)
    if ($turns -gt 0) { $args += @('--turns', $turns) }
    cmd /c ('"{0}" {1} > "{2}" 2>&1' -f $Python, ($args -join ' '), $log)
    if (-not (Test-Path $out)) { throw "测量失败：$scenario/$tag（见 $log）" }
    return Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-Avg($runs, [string]$prop) {
    $vals = @($runs | ForEach-Object { $_.$prop })
    if ($vals.Count -eq 0) { return 0 }
    return [math]::Round((($vals | Measure-Object -Average).Average), 1)
}

$summary = @{}

# ================= E3：闸门（阈值调到 1，跑多次）=================
"`n--- E3：空结果闸门（阈值=1，{0} 次）---" -f $GateRuns
$gateOnRuns = @(); $gateOffRuns = @()

Stop-Agent
Start-Agent @{ ENABLE_EMPTY_SEARCH_GATE = 'true'; MAX_EMPTY_SEARCHES = '1' }
for ($i = 1; $i -le $GateRuns; $i++) {
    $r = Invoke-Measure 'gate' "on$i"
    $gateOnRuns += $r
    "  开 第{0}次：工具 {1} 次，tokens {2}，{3}ms，拦截 {4}" -f $i, $r.tool_call_count, $r.tokens_in, $r.latency_ms, $r.empty_search_blocks
}

Stop-Agent
Start-Agent @{ ENABLE_EMPTY_SEARCH_GATE = 'false'; MAX_EMPTY_SEARCHES = '1' }
for ($i = 1; $i -le $GateRuns; $i++) {
    $r = Invoke-Measure 'gate' "off$i"
    $gateOffRuns += $r
    "  关 第{0}次：工具 {1} 次，tokens {2}，{3}ms" -f $i, $r.tool_call_count, $r.tokens_in, $r.latency_ms
}

$summary['E3'] = @{
    gate_on  = @{
        calls  = (Get-Avg $gateOnRuns 'tool_call_count')
        tokens = (Get-Avg $gateOnRuns 'tokens_in')
        runs   = $gateOnRuns.Count
    }
    gate_off = @{
        calls  = (Get-Avg $gateOffRuns 'tool_call_count')
        tokens = (Get-Avg $gateOffRuns 'tokens_in')
        runs   = $gateOffRuns.Count
    }
    detail   = @{ on = $gateOnRuns; off = $gateOffRuns }
}

# ================= E4：故障注入 =================
"`n--- E4：后端不可达（重试 on/off）---"
# 指向一个没人监听的端口：请求必然在传输层失败
Stop-Agent
Start-Agent @{ BACKEND_BASE_URL = 'http://127.0.0.1:59999'; BACKEND_MAX_RETRIES = '2' }
$faultRetry = Invoke-Measure 'fault' 'retry'
"  重试=2：{0}ms，retries={1}，exhausted={2}，优雅降级={3}" -f `
    $faultRetry.latency_ms, $faultRetry.retries, $faultRetry.retry_exhausted, $faultRetry.graceful

Stop-Agent
Start-Agent @{ BACKEND_BASE_URL = 'http://127.0.0.1:59999'; BACKEND_MAX_RETRIES = '0' }
$faultNoRetry = Invoke-Measure 'fault' 'noretry'
"  重试=0：{0}ms，retries={1}，exhausted={2}，优雅降级={3}" -f `
    $faultNoRetry.latency_ms, $faultNoRetry.retries, $faultNoRetry.retry_exhausted, $faultNoRetry.graceful

$summary['E4'] = @{
    retry    = @{ ms = $faultRetry.latency_ms; retries = $faultRetry.retries; exhausted = $faultRetry.retry_exhausted; graceful = $faultRetry.graceful; reply = $faultRetry.reply }
    no_retry = @{ ms = $faultNoRetry.latency_ms; retries = $faultNoRetry.retries; exhausted = $faultNoRetry.retry_exhausted; graceful = $faultNoRetry.graceful; reply = $faultNoRetry.reply }
}

# ================= E2：30 轮压缩 =================
if (-not $SkipE2) {
    "`n--- E2：上下文压缩（{0} 轮）---" -f $Turns
    Stop-Agent
    Start-Agent @{ ENABLE_COMPRESSION = 'true' }
    $compOn = Invoke-Measure 'compress' 'on' $Turns
    "  开：总 tokens_in {0}，末 3 轮 {1}，压缩 {2} 次" -f $compOn.tokens_in_total, $compOn.tokens_in_last3, $compOn.compactions

    Stop-Agent
    Start-Agent @{ ENABLE_COMPRESSION = 'false' }
    $compOff = Invoke-Measure 'compress' 'off' $Turns
    "  关：总 tokens_in {0}，末 3 轮 {1}，压缩 {2} 次" -f $compOff.tokens_in_total, $compOff.tokens_in_last3, $compOff.compactions

    $pct = if ($compOff.tokens_in_total -gt 0) {
        [math]::Round(100.0 * ($compOff.tokens_in_total - $compOn.tokens_in_total) / $compOff.tokens_in_total, 1)
    } else { 0 }
    "  降幅：{0}%" -f $pct

    $summary['E2'] = @{
        on   = @{ total = $compOn.tokens_in_total; last3 = $compOn.tokens_in_last3; compactions = $compOn.compactions; probe = $compOn.probe_reply }
        off  = @{ total = $compOff.tokens_in_total; last3 = $compOff.tokens_in_last3; compactions = $compOff.compactions; probe = $compOff.probe_reply }
        drop = $pct
    }
}

$summary | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $LogDir 'ablation-agent2.json') -Encoding UTF8

Stop-Agent
Start-Agent @{}
"`n已恢复 agent（默认配置）"
"结果：$LogDir\ablation-agent2.json"
