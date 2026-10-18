# ============================================================
# 一键停止：后端(8081) + AI 助手(8090)
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File infra\stop-all.ps1
#
# 只停这两个服务，**不会**动 MySQL。
# ============================================================

foreach ($port in 8081, 8090) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $conns) {
        Write-Host "端口 $port 本来就没有服务" -ForegroundColor Gray
        continue
    }
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            try {
                Stop-Process -Id $proc.Id -Force
                Write-Host "已停止端口 $port 的进程 PID $($proc.Id) ($($proc.ProcessName))" -ForegroundColor Green
            } catch {
                Write-Host "停止 PID $($proc.Id) 失败：$($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
}
Start-Sleep -Seconds 2
Write-Host ''
foreach ($port in 8081, 8090) {
    $alive = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($alive) { Write-Host "端口 $port 仍在监听" -ForegroundColor Yellow }
    else        { Write-Host "端口 $port 已释放" -ForegroundColor Gray }
}
