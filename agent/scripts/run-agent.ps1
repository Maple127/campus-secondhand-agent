# ============================================================
# 启动 Agent 服务（开发用）
#
# 用法：
#   powershell -File scripts/run-agent.ps1
#
# 它会：
#   1. 从环境变量或 DSH 凭据库读取 DEEPSEEK_API_KEY
#   2. 设置服务令牌与后端地址
#   3. 启动 uvicorn
#
# 注意：密钥只存在于进程环境变量中，不会写入任何文件。
# ============================================================

$ErrorActionPreference = 'Stop'
$agentDir = Split-Path -Parent $PSScriptRoot
Set-Location $agentDir

$python = Join-Path $agentDir '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Error "未找到虚拟环境。请先执行：`n  py -3.11 -m venv .venv`n  .venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# ---------- LLM Key ----------
if (-not $env:DEEPSEEK_API_KEY) {
    $envFile = Join-Path $agentDir '.env'
    if (Test-Path $envFile) {
        Write-Host "从 .env 读取配置" -ForegroundColor Cyan
    } else {
        # 回退：从 DSH 凭据库读取（本机开发环境）
        $cred = Join-Path $env:USERPROFILE '.dsh\.credentials.yaml'
        if (Test-Path $cred) {
            $m = [regex]::Match((Get-Content $cred -Raw), 'DEEPSEEK_API_KEY:\s*"?([^"\r\n]+)"?')
            if ($m.Success) {
                $env:DEEPSEEK_API_KEY = $m.Groups[1].Value.Trim()
                Write-Host "已从 DSH 凭据库加载 DEEPSEEK_API_KEY" -ForegroundColor Cyan
            }
        }
    }
}

if (-not $env:DEEPSEEK_API_KEY) {
    Write-Error "缺少 DEEPSEEK_API_KEY。请复制 .env.example 为 .env 并填写，或设置同名环境变量。"
}

# ---------- 其它配置 ----------
if (-not $env:AGENT_SERVICE_TOKEN)  { $env:AGENT_SERVICE_TOKEN  = 'demo-agent-token-local' }
if (-not $env:BACKEND_BASE_URL)     { $env:BACKEND_BASE_URL     = 'http://localhost:8081' }

Write-Host ""
Write-Host "  Agent 服务启动中..." -ForegroundColor Green
Write-Host "  后端     : $env:BACKEND_BASE_URL"
Write-Host "  调试台   : http://127.0.0.1:8090/playground"
Write-Host "  API 文档 : http://127.0.0.1:8090/docs"
Write-Host ""

& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8090 --reload
