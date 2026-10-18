# ============================================================
# 一键启动：MySQL 检查 + 后端(8081) + AI 助手(8090)
#
# 用法（在项目根目录）：
#   powershell -ExecutionPolicy Bypass -File infra\start-all.ps1
#
# 说明：
#   · 后端必须连 MySQL 8.0.41（IPv6 [::1]），见 backend/application.properties
#   · AI 助手需要 DEEPSEEK_API_KEY，脚本会依次尝试：
#       环境变量 → agent\.env → DSH 凭据库
# ============================================================

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $root 'infra'

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

# ---------- 1. 检查 MySQL 8.0（IPv6） ----------
Step '检查 MySQL 8.0 (IPv6 [::1]:3306)'
$mysql = 'D:\Develop\MySQL\MySQL Server 8.0\bin\mysql.exe'
if (Test-Path $mysql) {
    # 用 MYSQL_PWD 传密码：命令行带 -p 会往 stderr 打警告，
    # 而本脚本 ErrorActionPreference=Stop 会把那条警告当成致命错误。
    $oldPwd = $env:MYSQL_PWD
    $env:MYSQL_PWD = '123456'
    $ver = $null
    try {
        $ver = (& $mysql -h ::1 -P 3306 -uroot -N -e "SELECT VERSION();" 2>$null | Select-Object -First 1)
    } catch {
        $ver = $null
    } finally {
        $env:MYSQL_PWD = $oldPwd
    }
    if ($ver -match '^8\.') {
        Ok "MySQL $ver 可连接"
    } else {
        Warn "连不上 8.0 实例（返回：$ver）。请确认 MySQL80 服务在运行：Get-Service MySQL80"
    }
} else {
    Warn "没找到 mysql.exe：$mysql（只影响检查，不影响启动）"
}

# ---------- 2. 启动后端 ----------
Step '启动后端 (8081)'
$jar = Join-Path $root 'backend\target\campus-backend-0.2.0-SNAPSHOT.jar'
if (-not (Test-Path $jar)) {
    Warn '找不到 jar，正在编译（约 1~2 分钟）…'
    Push-Location (Join-Path $root 'backend')
    & mvn -B -DskipTests package | Out-Null
    Pop-Location
}
if (Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue) {
    Ok '8081 已在运行，跳过'
} else {
    $java = Join-Path $env:JAVA_HOME 'bin\java.exe'
    if (-not (Test-Path $java)) { $java = 'java' }
    Start-Process -FilePath $java -ArgumentList '-jar', $jar `
        -WorkingDirectory (Join-Path $root 'backend') `
        -RedirectStandardOutput (Join-Path $logDir '_backend.log') `
        -RedirectStandardError  (Join-Path $logDir '_backend-err.log') `
        -WindowStyle Hidden
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue) { break }
    }
    if (Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue) {
        Ok '后端已启动'
    } else {
        Warn '后端没起来，看日志 infra\_backend.log'
    }
}

# ---------- 3. 启动 AI 助手 ----------
Step '启动 AI 助手 (8090)'
if (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue) {
    Ok '8090 已在运行，跳过'
} else {
    $py = Join-Path $root 'agent\.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) {
        Warn '找不到 agent 虚拟环境，请先执行：'
        Write-Host '      cd agent' -ForegroundColor Gray
        Write-Host '      py -3.11 -m venv .venv' -ForegroundColor Gray
        Write-Host '      .venv\Scripts\python.exe -m pip install -r requirements.txt' -ForegroundColor Gray
    } else {
        # 取 API Key
        if (-not $env:DEEPSEEK_API_KEY) {
            $envFile = Join-Path $root 'agent\.env'
            if (Test-Path $envFile) {
                $m = [regex]::Match((Get-Content $envFile -Raw), 'DEEPSEEK_API_KEY\s*=\s*(\S+)')
                if ($m.Success) { $env:DEEPSEEK_API_KEY = $m.Groups[1].Value.Trim() }
            }
        }
        if (-not $env:DEEPSEEK_API_KEY) {
            $cred = Join-Path $env:USERPROFILE '.dsh\.credentials.yaml'
            if (Test-Path $cred) {
                $m = [regex]::Match((Get-Content $cred -Raw), 'DEEPSEEK_API_KEY:\s*"?([^"\r\n]+)"?')
                if ($m.Success) { $env:DEEPSEEK_API_KEY = $m.Groups[1].Value.Trim() }
            }
        }
        if (-not $env:DEEPSEEK_API_KEY) {
            Warn '没有 DEEPSEEK_API_KEY —— AI 助手会启动失败。请在 agent\.env 里填写。'
        } else {
            Ok '已获取 DEEPSEEK_API_KEY'
        }
        $env:AGENT_SERVICE_TOKEN = 'demo-agent-token-local'
        $env:BACKEND_BASE_URL    = 'http://localhost:8081'
        Start-Process -FilePath $py `
            -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8090' `
            -WorkingDirectory (Join-Path $root 'agent') `
            -RedirectStandardOutput (Join-Path $logDir '_agent.log') `
            -RedirectStandardError  (Join-Path $logDir '_agent-err.log') `
            -WindowStyle Hidden
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue) { break }
        }
        if (Get-NetTCPConnection -LocalPort 8090 -State Listen -ErrorAction SilentlyContinue) {
            Ok 'AI 助手已启动'
        } else {
            Warn 'AI 助手没起来，看日志 infra\_agent.log'
        }
    }
}

# ---------- 4. 汇总 ----------
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' 网站（前端）      http://localhost:8081' -ForegroundColor White
Write-Host ' AI 调试台         http://127.0.0.1:8090/playground' -ForegroundColor White
Write-Host ' AI 接口文档       http://127.0.0.1:8090/docs' -ForegroundColor White
Write-Host ''
Write-Host ' 普通用户          user01 / pass123' -ForegroundColor Gray
Write-Host ' 管理员            admin  / admin' -ForegroundColor Gray
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''
Write-Host ' 按 Ctrl+C 不会停服务；要停请运行：' -ForegroundColor Gray
Write-Host '   powershell -ExecutionPolicy Bypass -File infra\stop-all.ps1' -ForegroundColor Gray
