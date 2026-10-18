# 消融评测 E2/E3：上下文压缩、空结果闸门
#
# 两个实验都靠**服务启动时的环境变量**切换开关，所以每次测量前要重启 agent。
#
#   E3 闸门：问一件平台上没有的东西，看模型会搜几次
#   E2 压缩：跑 12 轮对话，看 token 增长曲线 + 最后考一次"约束还记得吗"
#
# 压缩的预算故意调小（1500），否则 12 轮根本达不到 6000 的默认阈值，
# 实验会变成"两个条件完全一样"。

param(
    [string]$LogDir = 'D:\Develop\AI\deepseek\test2\infra',
    [string]$Python = 'D:\Develop\AI\deepseek\test2\agent\.venv\Scripts\python.exe',
    [string]$AgentDir = 'D:\Develop\AI\deepseek\test2\agent',
    [int]$Turns = 12
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
    Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

function Start-Agent([hashtable]$extraEnv) {
    $psi = @{
        AGENT_SERVICE_TOKEN = 'demo-agent-token-local'
        BACKEND_BASE_URL    = 'http://localhost:8081'
        DEEPSEEK_API_KEY    = (Get-ApiKey)
        # 两个实验共用的小预算：让压缩在 12 轮内真的触发
        CONTEXT_TOKEN_BUDGET = '1500'
    }
    foreach ($k in $extraEnv.Keys) { $psi[$k] = $extraEnv[$k] }

    # 用 Start-Process + env 无法直接传变量，这里改用 ProcessStartInfo
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Python
    $info.Arguments = '-m uvicorn app.main:app --host 127.0.0.1 --port 8090'
    $info.WorkingDirectory = $AgentDir
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.CreateNoWindow = $true
    foreach ($k in $psi.Keys) { $info.EnvironmentVariables[$k] = [string]$psi[$k] }
    $proc = [System.Diagnostics.Process]::Start($info)
    # 不读走管道会阻塞子进程
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest 'http://127.0.0.1:8090/health' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { Start-Sleep -Seconds 2; return }
        } catch { }
    }
    throw 'agent 120 秒内未就绪'
}

function Invoke-Measure([string]$scenario, [string]$tag) {
    $out = Join-Path $LogDir ("_abl_{0}_{1}.json" -f $scenario, $tag)
    $args = @((Join-Path (Join-Path $AgentDir 'scripts') 'measure_ablation.py'),
        '--scenario', $scenario, '--out', $out)
    if ($scenario -eq 'compress') { $args += @('--turns', $Turns) }

    # 走 cmd 重定向，避免把 python 的 stderr 当致命错误
    $log = Join-Path $LogDir ("_abl_{0}_{1}.log" -f $scenario, $tag)
    $cmdLine = '"{0}" {1} > "{2}" 2>&1' -f $Python, ($args -join ' '), $log
    cmd /c $cmdLine
    if (-not (Test-Path $out)) { throw "测量失败（无输出文件）：$scenario/$tag，见 $log" }
    return Get-Content $out -Raw -Encoding UTF8 | ConvertFrom-Json
}

"=== 消融评测（agent 侧）==="
$summary = @{}

# ---------------- E3：空结果闸门 ----------------
"`n--- E3：空结果重试闸门 ---"
Stop-Agent
Start-Agent @{ ENABLE_EMPTY_SEARCH_GATE = 'true' }
$gateOn = Invoke-Measure 'gate' 'on'
"  闸门＝开：工具调用 {0} 次，tokens {1}，{2}ms" -f $gateOn.tool_call_count, $gateOn.tokens_in, $gateOn.latency_ms

Stop-Agent
Start-Agent @{ ENABLE_EMPTY_SEARCH_GATE = 'false' }
$gateOff = Invoke-Measure 'gate' 'off'
"  闸门＝关：工具调用 {0} 次，tokens {1}，{2}ms" -f $gateOff.tool_call_count, $gateOff.tokens_in, $gateOff.latency_ms

$summary['E3'] = @{
    gate_on  = @{ calls = $gateOn.tool_call_count; tokens = $gateOn.tokens_in; ms = $gateOn.latency_ms }
    gate_off = @{ calls = $gateOff.tool_call_count; tokens = $gateOff.tokens_in; ms = $gateOff.latency_ms }
}

# ---------------- E2：上下文压缩 ----------------
"`n--- E2：上下文压缩（{0} 轮）---" -f $Turns
Stop-Agent
Start-Agent @{ ENABLE_COMPRESSION = 'true' }
$compOn = Invoke-Measure 'compress' 'on'
"  压缩＝开：总 tokens_in {0}，末 3 轮合计 {1}，压缩 {2} 次（省约 {3}）" -f `
    $compOn.tokens_in_total, $compOn.tokens_in_last3, $compOn.compactions, $compOn.tokens_saved_by_compaction

Stop-Agent
Start-Agent @{ ENABLE_COMPRESSION = 'false' }
$compOff = Invoke-Measure 'compress' 'off'
"  压缩＝关：总 tokens_in {0}，末 3 轮合计 {1}，压缩 {2} 次" -f `
    $compOff.tokens_in_total, $compOff.tokens_in_last3, $compOff.compactions

$summary['E2'] = @{
    on  = @{ total = $compOn.tokens_in_total; last3 = $compOn.tokens_in_last3; compactions = $compOn.compactions; saved = $compOn.tokens_saved_by_compaction; probe = $compOn.probe_reply }
    off = @{ total = $compOff.tokens_in_total; last3 = $compOff.tokens_in_last3; compactions = $compOff.compactions; probe = $compOff.probe_reply }
}

$summary | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $LogDir 'ablation-agent.json') -Encoding UTF8

# ---------------- 恢复默认 ----------------
Stop-Agent
Start-Agent @{}
"`n已恢复 agent（默认配置）"
"结果：$LogDir\ablation-agent.json"
