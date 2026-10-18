# 消融评测 E1：品类词扩展到底贡献了多少召回
#
# 做法：同一批查询，分别在「品类词开 / 关」两种后端配置下跑一遍，对比召回。
#
# 为什么必须重跑而不是拿历史数字相减：
#   我们之前说的「19/30 → 28/30」是**不同时期、不同数据集**上测的
#   （中间商品从 22 件扩到 158 件）。两个数字不能直接相减，
#   差值里有数据变化，不只是品类词的贡献。
#
# 复用 infra/tag-verify-api.py 作为唯一的用例来源，避免两份查询清单漂移。

param(
    [string]$Jar = 'D:\Develop\AI\deepseek\test2\backend\target\campus-backend-0.2.0-SNAPSHOT.jar',
    [string]$LogDir = 'D:\Develop\AI\deepseek\test2\infra',
    [string]$Python = 'D:\Develop\AI\deepseek\test2\agent\.venv\Scripts\python.exe'
)

$ErrorActionPreference = 'Stop'
$verify = 'D:\Develop\AI\deepseek\test2\infra\tag-verify-api.py'

function Stop-Backend {
    Get-NetTCPConnection -LocalPort 8081 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
}

function Start-Backend([string[]]$extraArgs) {
    $log = Join-Path $LogDir '_backend_ablation.log'
    $argList = @('-jar', $Jar) + $extraArgs
    Start-Process -FilePath "$env:JAVA_HOME\bin\java.exe" -ArgumentList $argList `
        -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    # 端口在听 ≠ 服务就绪：JVM 起得慢，DispatcherServlet/JPA 初始化完成前
    # 打业务接口会 404/500。这里直接轮询一个真实页面。
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest 'http://localhost:8081/home' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return }
        } catch { }
    }
    throw '后端 120 秒内未就绪（/home 未返回 200）'
}

function Measure-Recall([string]$label) {
    # 走 cmd 重定向，避免 PowerShell 把 python 的普通 stderr 当成致命错误
    $tmp = Join-Path $LogDir '_verify_out.txt'
    cmd /c "`"$Python`" `"$verify`" > `"$tmp`" 2>&1"
    $out = Get-Content $tmp -Raw -Encoding UTF8
    $m = [regex]::Match($out, '全部召回\s+(\d+)/(\d+)')
    if (-not $m.Success) {
        "  {0}: 未解析到结果，原始输出末尾：" -f $label
        ($out -split "`n" | Select-Object -Last 5) -join "`n"
        throw "解析失败: $label"
    }
    $hit = [int]$m.Groups[1].Value
    $total = [int]$m.Groups[2].Value
    $rate = [math]::Round(100.0 * $hit / $total, 1)
    "  {0,-12} 召回 {1}/{2}（{3}%）" -f $label, $hit, $total, $rate
    return @{ label = $label; hit = $hit; total = $total; rate = $rate }
}

"=== E1：品类词扩展消融 ==="
$off = $null; $on = $null
try {
    Stop-Backend
    Start-Backend @('--app.search.type-match-enabled=false')
    $off = Measure-Recall '品类词＝关'

    Stop-Backend
    Start-Backend @('--app.search.type-match-enabled=true')
    $on = Measure-Recall '品类词＝开'

    ""
    "=== 结论 ==="
    $delta = $on.rate - $off.rate
    "  召回率：{0}% → {1}%（{2}{3} 个百分点）" -f `
        $off.rate, $on.rate, $(if ($delta -ge 0) { '+' } else { '' }), [math]::Round($delta, 1)
    "  多召回：{0} 条" -f ($on.hit - $off.hit)

    @{ experiment = 'E1-tag-matching'; off = $off; on = $on } |
        ConvertTo-Json -Depth 5 | Set-Content (Join-Path $LogDir 'ablation-e1.json') -Encoding UTF8
    "已写入 $LogDir\ablation-e1.json"
}
finally {
    Stop-Backend
    Start-Backend @()
    "已恢复后端（默认配置）"
}
