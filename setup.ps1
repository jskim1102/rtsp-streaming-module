# 설치 스크립트 (윈도우) — git clone 한 폴더에서 setup.cmd 를 더블클릭하면 설치·실행까지 끝.
# 다시 실행해도 안전하다: 이미 채운 .env 값은 그대로 두고, 새 버전 이미지를 받아 다시 켠다.
#
# 하네스 정본: harness-claude/engine/templates/setup/setup.ps1 — 이 파일을 빌드에서 고치지 말 것.
# 배포 검사(./run.sh release)가 정본과 같은지 비교한다. 규칙 = harness-claude/docs/release.md
# 이 파일은 UTF-8 (BOM 있음) 이어야 한다 — Windows PowerShell 5.1 이 한글을 깨뜨리지 않게.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Root = $PSScriptRoot
Set-Location -LiteralPath $Root

function Step($m) { Write-Host ''; Write-Host "> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "  OK $m" }
function Warn($m) { Write-Host "  !  $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host ''; Write-Host "X $m" -ForegroundColor Red; exit 1 }

# ── 1. Docker ──
Step 'Docker 확인'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Die 'Docker Desktop 이 없어요. https://docs.docker.com/desktop/setup/install/windows-install/ 에서 설치한 뒤 다시 실행하세요.'
}
$null = & docker info 2>&1
if ($LASTEXITCODE -ne 0) { Die 'Docker Desktop 이 꺼져 있어요. Docker Desktop 을 켜고, 다 켜질 때까지 기다린 뒤 다시 실행하세요.' }
$null = & docker compose version 2>&1
if ($LASTEXITCODE -ne 0) { Die 'docker compose 가 없어요. Docker Desktop 을 최신으로 업데이트하세요.' }
Ok 'Docker 사용 가능'

# ── 2. .env ──
$EnvPath = Join-Path $Root '.env'
$ExPath = Join-Path $Root '.env.example'
$Utf8 = New-Object System.Text.UTF8Encoding $false
function EnvGet($k) { $v = $null; foreach ($l in $script:Lines) { if ($l.StartsWith("$k=")) { $v = $l.Substring($k.Length + 1) } }; return $v }
function EnvSet($k, $v) {
  for ($i = 0; $i -lt $script:Lines.Count; $i++) { if ($script:Lines[$i].StartsWith("$k=")) { $script:Lines[$i] = "$k=$v"; return } }
  [void]$script:Lines.Add("$k=$v")
}
function EnvDel($k) { $script:Lines = [Collections.ArrayList]@($script:Lines | Where-Object { -not $_.StartsWith("$k=") }) }
function EnvSave { [IO.File]::WriteAllText($EnvPath, (($script:Lines -join "`n") + "`n"), $Utf8) }  # LF — compose 가 읽는 형식
function Rand { $b = New-Object byte[] 12; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') }) }
# Hyper-V·WSL 이 막아 둔 포트 구간 — 비어 보여도 Docker 가 못 쓴다
$Excluded = @()
foreach ($l in (& netsh interface ipv4 show excludedportrange protocol=tcp 2>$null)) {
  if ($l -match '^\s*(\d+)\s+(\d+)') { $Excluded += , @([int]$matches[1], [int]$matches[2]) }
}
function PortBusy([int]$p) {
  foreach ($r in $Excluded) { if ($p -ge $r[0] -and $p -le $r[1]) { return $true } }
  if (Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue) { return $true }
  if (Get-NetUDPEndpoint -LocalPort $p -ErrorAction SilentlyContinue) { return $true }
  return $false
}

Step '설정 파일 (.env)'
if (-not (Test-Path -LiteralPath $ExPath)) { Die '.env.example 이 없어요 - 올바른 폴더인지 확인하세요.' }
$fresh = $false
if (Test-Path -LiteralPath $EnvPath) {
  $script:Lines = [Collections.ArrayList]@([IO.File]::ReadAllLines($EnvPath))
} else {
  $script:Lines = [Collections.ArrayList]@([IO.File]::ReadAllLines($ExPath)); $fresh = $true; Ok '.env.example -> .env 복사'
}
$asks = [ordered]@{}; $q = $null; $newKeys = @{}
foreach ($line in [IO.File]::ReadAllLines($ExPath)) {  # .env.example 에 새로 생긴 항목 덧붙이기 + '# 묻기:' 질문 모으기
  if ($line.StartsWith('# 묻기:')) { $q = $line.Substring(5).Trim(); continue }
  if ($line -match '^([A-Za-z0-9_]+)=') {
    $k = $matches[1]
    if ($q) { $asks[$k] = $q }
    if ($null -eq (EnvGet $k)) { [void]$script:Lines.Add($line); $newKeys[$k] = 1; Ok "새 항목 $k" }
  }
  $q = $null
}
$keys = @($script:Lines | Where-Object { $_ -match '^[A-Za-z0-9_]+=' } | ForEach-Object { $_.Split('=')[0] })
$used = @{}
foreach ($k in $keys) { if ($k.EndsWith('_PORT')) { $v = EnvGet $k; if ($v) { $used[$v] = 1 } } }
$next = 18000
foreach ($k in $keys) {
  $v = EnvGet $k
  if ($k.EndsWith('_PORT')) {
    # 빈 칸이거나, 방금 복사한 기본값이 이 PC 에서 이미 쓰이는 중이면 빈 포트를 고른다
    if (-not $v -or ($fresh -and (PortBusy ([int]$v)))) {
      while ((PortBusy $next) -or $used.ContainsKey("$next")) { $next++ }
      EnvSet $k "$next"; $used["$next"] = 1; Ok "$k=$next"; $next++
    }
  } elseif ($k.EndsWith('_PASS') -or $k.EndsWith('_SECRET')) {
    if (-not $v) { EnvSet $k (Rand); Ok "$k 자동 생성" }
  }
}
# 설치하는 사람만 아는 값 — .env.example 에서 바로 윗줄이 '# 묻기: <질문>' 인 칸. 짐작해서 채우지 않고 묻는다.
# 처음 설치할 때와 새로 생긴 칸만 (다시 실행할 때마다 묻지 않음). Enter = 비워 둠.
if ($asks.Count -gt 0) {
  # 참고용 이 PC 주소 — WSL·Hyper-V 가상 어댑터(vEthernet)는 빼고
  $ips = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
      $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' -and $_.InterfaceAlias -notlike 'vEthernet*' } |
    ForEach-Object { "$($_.IPAddress)($($_.InterfaceAlias))" }) -join ' '
  foreach ($k in @($asks.Keys)) {
    if (EnvGet $k) { continue }
    if (-not ($fresh -or $newKeys.ContainsKey($k))) { continue }
    if ([Console]::IsInputRedirected) { Warn "$k 비워 둠 (물어볼 화면 없음) - 필요하면 .env 에 직접 쓰고 다시 실행"; continue }
    Write-Host ''; Write-Host "  ? $($asks[$k])"
    if (($k.EndsWith('_HOST') -or $k.EndsWith('_IP')) -and $ips) { Write-Host "    참고 - 이 PC 의 IP: $ips" }
    $ans = "$(Read-Host '  ')".Trim()
    if ($ans) { EnvSet $k $ans; Ok "$k=$ans" } else { Ok "$k 비워 둠" }
  }
}

# ── 3. GPU ──
Step 'GPU 확인'
$gpu = $false
if (Test-Path -LiteralPath (Join-Path $Root 'docker-compose.gpu.yml')) {
  if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $null = & nvidia-smi -L 2>&1
    if ($LASTEXITCODE -eq 0) { $gpu = $true; Ok 'NVIDIA GPU 사용' }
  }
  if (-not $gpu) { Ok 'GPU 없음 -> CPU 로 실행 (느릴 수 있어요)' }
} else {
  Ok '이 프로그램은 GPU 를 쓰지 않아요'
}
if ($gpu) {
  EnvSet 'COMPOSE_PATH_SEPARATOR' ':'
  EnvSet 'COMPOSE_FILE' 'docker-compose.yml:docker-compose.gpu.yml'
} else {
  EnvDel 'COMPOSE_FILE'; EnvDel 'COMPOSE_PATH_SEPARATOR'
}
EnvSave

# ── 4. 모델 파일 ──
$Weights = Join-Path $Root 'weights.txt'
if (Test-Path -LiteralPath $Weights) {
  Step '모델 파일 받기'
  if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { Die 'curl.exe 가 없어요. 윈도우를 업데이트한 뒤 다시 실행하세요.' }
  foreach ($line in [IO.File]::ReadAllLines($Weights)) {
    $f = $line.Trim() -split '\s+'
    if (-not $f[0] -or $f[0].StartsWith('#')) { continue }
    $path = Join-Path $Root $f[0]
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 0) { Ok "$($f[0]) (이미 있음)"; continue }
    $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path)
    & curl.exe -fL --retry 3 -o "$path.part" $f[1]
    if ($LASTEXITCODE -ne 0) { Die "$($f[0]) 를 받지 못했어요: $($f[1])" }
    Move-Item -Force -LiteralPath "$path.part" -Destination $path; Ok $f[0]
  }
}

# ── 5. 받기·만들기·켜기 ──
Step '설정 검사'
$out = & docker compose config -q 2>&1 | Out-String
if ($LASTEXITCODE -ne 0) { Die ".env 설정이 덜 됐어요 - .env 를 메모장으로 열어 아래 항목을 채운 뒤 다시 실행하세요:`n$out" }
Ok '설정 정상'

Step '프로그램 받기 (처음엔 몇 분 걸려요)'
$cfg = (& docker compose config --format json 2>$null) -join "`n" | ConvertFrom-Json
$pull = @(); $build = @()
foreach ($s in $cfg.services.PSObject.Properties) {
  if ("$($s.Value.image)".StartsWith('ghcr.io/')) { $pull += $s.Name }
  elseif ($s.Value.build) { $build += $s.Name }
}
foreach ($svc in $pull) {
  & docker compose pull $svc
  if ($LASTEXITCODE -eq 0) { Ok "$svc 받음" }
  else { Warn "$svc 이미지를 못 받았어요 -> 이 PC 에서 직접 만들어요 (오래 걸려요)"; $build += $svc }
}
if ($build.Count -gt 0) {
  Step "이 PC 에서 만들기: $($build -join ' ')"
  & docker compose build @build
  if ($LASTEXITCODE -ne 0) { Die '만들기에 실패했어요. 위 오류를 개발자에게 보내 주세요.' }
}

Step '켜기 (다 켜질 때까지 기다려요)'
& docker compose up -d --wait --wait-timeout 900
if ($LASTEXITCODE -ne 0) {
  & docker compose ps
  Die "켜지지 않았어요. 'docker compose logs' 출력을 개발자에게 보내 주세요."
}

$port = EnvGet 'FRONTEND_PORT'; if (-not $port) { $port = EnvGet 'BACKEND_PORT' }
Write-Host ''
Write-Host "설치 끝 - 브라우저에서 http://localhost:$port" -ForegroundColor Green
Write-Host '   끄기: docker compose down   다시 켜기: docker compose up -d   업데이트: git pull 후 setup.cmd'
