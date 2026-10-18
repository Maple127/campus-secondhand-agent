# 消融评测 E5：显式路由（FAST vs AGENT）
#
# 问题：把"简单检索"从 agent 循环里摘出来走快路径，到底省多少？
#
# 做法：同一组检索问句，分别在「快路径开」和「快路径关（全走 agent）」下各跑一遍。
#      关开关时路由仍然判为 FAST，但被配置降级为 AGENT —— 这样两组走的是同一批问句。
#
# 注意：这是一个**成本**实验，不是效果实验。
# 快路径能答的范围比 agent 窄（不做多步、不处理空结果），
# 所以"省了多少"必须和"少覆盖了多少"一起看。

param(
    [string]$LogDir = 'D:\Develop\AI\deepseek\test2\infra',
    [string]$Python = 'D:\Develop\AI\deepseek\test2\agent\.venv\Scripts\python.exe',
    [string]$AgentDir = 'D:\Develop\AI\deepseek\test2\agent'
)

$ErrorActionPreference = 'Stop'

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
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*uvicorn*app.main*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 25; $i++) {
        if (-not (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Seconds 1
    }
    throw '8090 端口未释放'
}

function Start-Agent([hashtable]$extraEnv) {
    $envs = @{
        AGENT_SERVICE_TOKEN = 'demo-agent-token-local'
        BACKEND_BASE_URL    = 'http://localhost:8081'
        DEEPSEEK_API_KEY    = (Get-ApiKey)
    }
    foreach ($k in $extraEnv.Keys) { $envs[$k] = $extraEnv[$k] }
    foreach ($k in $envs.Keys) { Set-Item -Path ("env:" + $k) -Value ([string]$envs[$k]) }

    Start-Process -FilePath $Python `
        -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8090' `
        -WorkingDirectory $AgentDir -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $LogDir '_agent_out.log') `
        -RedirectStandardError (Join-Path $LogDir '_agent_err.log')

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try {
            if ((Invoke-WebRequest 'http://127.0.0.1:8090/health' -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200) { return }
        } catch { }
    }
    Get-Content (Join-Path $LogDir '_agent_err.log') -Tail 15 -ErrorAction SilentlyContinue
    throw 'agent 未就绪'
}

function Invoke-Measure([string]$tag) {
    $out = Join-Path $LogDir ("_abl5_lookup_{0}.json" -f $tag)
    $log = Join-Path $LogDir ("_abl5_lookup_{0}.log" -f $tag)
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    $script = Join-Path (Join-Path $AgentDir 'scripts') 'measure_ablation.py'
    cmd /c ('"{0}" "{1}" --scenario lookup --out "{2}" > "{3}" 2>&1' -f $Python, $script, $out, $log)
    if (-not (Test-Path $out)) { throw "测量失败：$tag（见 $log）" }
    return Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json
}

"=== E5：显式路由（FAST vs AGENT）==="

Stop-Agent
Start-Agent @{ ENABLE_FAST_PATH = 'true' }
$fast = Invoke-Measure 'fast'
"  快路径＝开：平均 {0}ms，平均 tokens_in {1}，全部作答={2}" -f `
    $fast.avg_latency_ms, $fast.avg_tokens_in, $fast.all_answered
$fast.runs | ForEach-Object { "    {0,-18} {1,-6} {2,5}ms in={3,5}" -f $_.query, $_.strategy, $_.latency_ms, $_.tokens_in }

Stop-Agent
Start-Agent @{ ENABLE_FAST_PATH = 'false' }
$agent = Invoke-Measure 'agent'
"  快路径＝关：平均 {0}ms，平均 tokens_in {1}，全部作答={2}" -f `
    $agent.avg_latency_ms, $agent.avg_tokens_in, $agent.all_answered
$agent.runs | ForEach-Object { "    {0,-18} {1,-6} {2,5}ms in={3,5}" -f $_.query, $_.strategy, $_.latency_ms, $_.tokens_in }

$speedup = [math]::Round(100.0 * ($agent.avg_latency_ms - $fast.avg_latency_ms) / $agent.avg_latency_ms, 1)
$tokenCut = [math]::Round(100.0 * ($agent.avg_tokens_in - $fast.avg_tokens_in) / [math]::Max($agent.avg_tokens_in, 1), 1)

""
"=== 结论 ==="
"  延迟：{0}ms → {1}ms（快 {2}%）" -f $agent.avg_latency_ms, $fast.avg_latency_ms, $speedup
"  输入 token：{0} → {1}（省 {2}%）" -f $agent.avg_tokens_in, $fast.avg_tokens_in, $tokenCut

@{ experiment = 'E5-fast-path'; fast = $fast; agent = $agent } |
    ConvertTo-Json -Depth 6 | Set-Content (Join-Path $LogDir 'ablation-e5.json') -Encoding UTF8

Stop-Agent
Start-Agent @{}
"`n已恢复 agent（默认配置）"
"结果：$LogDir\ablation-e5.json"
