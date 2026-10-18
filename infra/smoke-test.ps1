# Agent REST API + security verification script
$ErrorActionPreference = 'Continue'
$base = 'http://localhost:8081'
$svc  = 'demo-agent-token-local'
$results = @()

function Record($name, $ok, $detail) {
    $script:results += [pscustomobject]@{ Test = $name; Pass = $ok; Detail = $detail }
    $mark = if ($ok) { 'PASS' } else { 'FAIL' }
    "{0,-4} {1,-46} {2}" -f $mark, $name, $detail
}

# ---------- 1. login (browser session) ----------
$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "$base/doLogin" -Method POST -Body @{username='user01';password='pass123'} `
    -WebSession $sess -UseBasicParsing -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
$loggedIn = $sess.Cookies.Count -gt 0
Record 'browser login' $loggedIn "cookies=$($sess.Cookies.Count)"

# ---------- 2. issue capability token ----------
$token = $null
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/agent/session" -Method POST -WebSession $sess `
        -Headers @{ 'X-Service-Token' = $svc } -ContentType 'application/json' -Body '{}'
    $token = $r.data.actorToken
    Record 'issue capability token' ($null -ne $token) "scopes=$($r.data.scopes -join ',')"
} catch {
    Record 'issue capability token' $false $_.Exception.Message
}

$h = @{ 'X-Service-Token' = $svc; 'X-Actor-Token' = $token }

# ---------- 3. missing service token must be rejected ----------
try {
    Invoke-RestMethod -Uri "$base/api/v1/products?size=3" -Headers @{ 'X-Actor-Token' = $token } | Out-Null
    Record 'reject missing service token' $false 'request unexpectedly succeeded'
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Record 'reject missing service token' ($code -eq 401) "http=$code"
}

# ---------- 4. wrong service token must be rejected ----------
try {
    Invoke-RestMethod -Uri "$base/api/v1/products?size=3" -Headers @{ 'X-Service-Token'='wrong'; 'X-Actor-Token'=$token } | Out-Null
    Record 'reject wrong service token' $false 'request unexpectedly succeeded'
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Record 'reject wrong service token' ($code -eq 401) "http=$code"
}

# ---------- 5. missing actor token must be rejected ----------
try {
    Invoke-RestMethod -Uri "$base/api/v1/products?size=3" -Headers @{ 'X-Service-Token'=$svc } | Out-Null
    Record 'reject missing actor token' $false 'request unexpectedly succeeded'
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Record 'reject missing actor token' ($code -eq 401) "http=$code"
}

# ---------- 6. search products ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/products?size=5" -Headers $h
    $n = $r.data.items.Count
    $allOnSale = ($r.data.items | Where-Object { $_.available -ne $true }).Count -eq 0
    Record 'search products' ($r.code -eq 0 -and $n -gt 0) "returned=$n total=$($r.data.totalElements)"
    Record 'search excludes non-orderable' $allOnSale 'all items available=true'
} catch {
    Record 'search products' $false $_.Exception.Message
}

# ---------- 7. search with price filter ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/products?minPrice=200&maxPrice=3000&size=20" -Headers $h
    $prices = $r.data.items | ForEach-Object { [double]$_.price }
    $inRange = ($prices | Where-Object { $_ -lt 200 -or $_ -gt 3000 }).Count -eq 0
    Record 'price range filter' $inRange "prices=$($prices -join ',')"
} catch {
    Record 'price range filter' $false $_.Exception.Message
}

# ---------- 8. price comparison ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/products/1/price-comparison" -Headers $h
    $d = $r.data
    Record 'price comparison' ($r.code -eq 0) "verdict=$($d.verdict) median=$($d.median) samples=$($d.sampleSize)"
} catch {
    Record 'price comparison' $false $_.Exception.Message
}

# ---------- 9. categories meta ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/meta/categories" -Headers $h
    Record 'categories meta' ($r.data.Count -gt 0) "count=$($r.data.Count)"
    $script:anyCategory = $r.data[0].name
} catch {
    Record 'categories meta' $false $_.Exception.Message
}

# ---------- 10. order flow: create on available product ----------
$avail = $null
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/products?size=50" -Headers $h
    $avail = $r.data.items | Where-Object { $_.available -eq $true -and $_.sellerId -ne 1 } | Select-Object -First 1
} catch {}
if ($avail) {
    try {
        $o = Invoke-RestMethod -Uri "$base/api/v1/orders" -Method POST -Headers $h `
             -ContentType 'application/json' -Body (@{ productId = $avail.id } | ConvertTo-Json)
        Record 'create order (agent)' ($o.code -eq 0) "orderNo=$($o.data.orderNo) productId=$($avail.id)"
        $script:createdOrder = $o.data.orderNo

        # product must now be unavailable
        $p = Invoke-RestMethod -Uri "$base/api/v1/products/$($avail.id)" -Headers $h
        Record 'product locked after order' ($p.data.available -eq $false) "status=$($p.data.status)/$($p.data.statusLabel)"

        # second order on same product must fail
        try {
            Invoke-RestMethod -Uri "$base/api/v1/orders" -Method POST -Headers $h `
                -ContentType 'application/json' -Body (@{ productId = $avail.id } | ConvertTo-Json) | Out-Null
            Record 'double-sell blocked (REST)' $false 'second order unexpectedly succeeded'
        } catch {
            $code = $_.Exception.Response.StatusCode.value__
            Record 'double-sell blocked (REST)' ($code -eq 409) "http=$code"
        }

        # cancel releases product
        $c = Invoke-RestMethod -Uri "$base/api/v1/orders/$script:createdOrder/cancel" -Method POST -Headers $h `
             -ContentType 'application/json' -Body '{"reason":"test"}'
        $p2 = Invoke-RestMethod -Uri "$base/api/v1/products/$($avail.id)" -Headers $h
        Record 'cancel releases product' ($p2.data.available -eq $true) "status=$($p2.data.statusLabel)"
    } catch {
        Record 'create order (agent)' $false $_.Exception.Message
    }
} else {
    Record 'create order (agent)' $false 'no available product owned by another user'
}

# ---------- 11. publish goes to pending review ----------
try {
    $body = @{ name = 'AGENT-SMOKE-TEST-ITEM'; price = 12.5; description = 'created by smoke test'; category = $script:anyCategory } | ConvertTo-Json
    $r = Invoke-RestMethod -Uri "$base/api/v1/products" -Method POST -Headers $h -ContentType 'application/json' -Body $body
    Record 'publish via agent' ($r.code -eq 0 -and $r.data.status -eq 'PENDING_APPROVAL') `
        "status=$($r.data.status)/$($r.data.statusLabel) id=$($r.data.id)"
    $script:newProductId = $r.data.id
} catch {
    Record 'publish via agent' $false $_.Exception.Message
}

# ---------- 12. scope escalation must be denied ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/agent/session" -Method POST -WebSession $sess `
        -Headers @{ 'X-Service-Token' = $svc } -ContentType 'application/json' `
        -Body '{"scopes":["product:read","order:pay","admin:everything"]}'
    $scopes = $r.data.scopes
    $escalated = $scopes -contains 'order:pay' -or $scopes -contains 'admin:everything'
    Record 'scope escalation denied' (-not $escalated) "granted=$($scopes -join ',')"
} catch {
    Record 'scope escalation denied' $false $_.Exception.Message
}

# ---------- 13. restricted token cannot publish ----------
try {
    $r = Invoke-RestMethod -Uri "$base/api/v1/agent/session" -Method POST -WebSession $sess `
        -Headers @{ 'X-Service-Token' = $svc } -ContentType 'application/json' `
        -Body '{"scopes":["product:read"]}'
    $roToken = $r.data.actorToken
    $roH = @{ 'X-Service-Token' = $svc; 'X-Actor-Token' = $roToken }
    $readOk = $false
    try { Invoke-RestMethod -Uri "$base/api/v1/products?size=1" -Headers $roH | Out-Null; $readOk = $true } catch {}
    $writeBlocked = $false
    try {
        Invoke-RestMethod -Uri "$base/api/v1/products" -Method POST -Headers $roH -ContentType 'application/json' `
            -Body '{"name":"x","price":1}' | Out-Null
    } catch {
        $writeBlocked = ($_.Exception.Response.StatusCode.value__ -eq 403)
    }
    Record 'read-only token can read' $readOk 'GET allowed'
    Record 'read-only token cannot publish' $writeBlocked 'POST -> 403'
} catch {
    Record 'read-only token cannot publish' $false $_.Exception.Message
}

# ---------- 14. unauthenticated session request ----------
try {
    Invoke-RestMethod -Uri "$base/api/v1/agent/session" -Method POST -Headers @{ 'X-Service-Token'=$svc } `
        -ContentType 'application/json' -Body '{}' | Out-Null
    Record 'session requires browser login' $false 'unexpectedly succeeded'
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Record 'session requires browser login' ($code -eq 401) "http=$code"
}

""
"==================== SUMMARY ===================="
$pass = ($results | Where-Object Pass).Count
$fail = ($results | Where-Object { -not $_.Pass }).Count
"TOTAL=$($results.Count)  PASS=$pass  FAIL=$fail"
if ($fail -gt 0) {
    "--- failures ---"
    $results | Where-Object { -not $_.Pass } | ForEach-Object { "  $($_.Test): $($_.Detail)" }
}
