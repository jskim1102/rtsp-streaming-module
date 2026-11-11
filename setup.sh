#!/usr/bin/env bash
# 설치 스크립트 (리눅스·맥) — git clone 한 폴더에서 `./setup.sh` 한 번이면 설치·실행까지 끝.
# 다시 실행해도 안전하다: 이미 채운 .env 값은 그대로 두고, 새 버전 이미지를 받아 다시 켠다.
#
# 하네스 정본: harness-claude/engine/templates/setup/setup.sh — 이 파일을 빌드에서 고치지 말 것.
# 배포 검사(./run.sh release)가 정본과 같은지 비교한다. 규칙 = harness-claude/docs/release.md
set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n▶ %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ! %s\n' "$*"; }
die()  { printf '\n✗ %s\n' "$*" >&2; exit 1; }

# ── 1. Docker ──
step "Docker 확인"
command -v docker >/dev/null 2>&1 \
  || die "Docker 가 없어요. https://docs.docker.com/get-docker/ 에서 설치한 뒤 다시 실행하세요."
if ! out=$(docker info 2>&1); then
  case "$out" in
    *"permission denied"*) die "이 사용자는 Docker 권한이 없어요. 'sudo usermod -aG docker \$USER' 실행 후 다시 로그인하세요." ;;
  esac
  die "Docker 가 꺼져 있어요. Docker Desktop(또는 docker 서비스)을 켠 뒤 다시 실행하세요."
fi
docker compose version >/dev/null 2>&1 || die "docker compose 가 없어요. Docker 를 최신으로 업데이트하세요."
ok "Docker 사용 가능"

# ── 2. .env ──
env_get() { sed -n "s/^$1=//p" .env | tail -1; }
env_set() {  # KEY VALUE — 있으면 바꾸고, 없으면 덧붙인다
  if grep -q "^$1=" .env; then
    (umask 077; K="$1" V="$2" awk 'index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; next } { print }' .env > .env.tmp)
    mv .env.tmp .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
env_del() { (umask 077; awk -v k="$1" 'index($0, k "=") != 1' .env > .env.tmp); mv .env.tmp .env; }
rand() { od -An -N12 -tx1 /dev/urandom | tr -d ' \n'; }
port_busy() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; then return 0; fi
  if command -v ss >/dev/null 2>&1; then
    ss -Htuln 2>/dev/null | awk '{print $5}' | grep -E "[:.]$1\$" >/dev/null && return 0
  elif command -v lsof >/dev/null 2>&1; then
    # busybox lsof(alpine)는 옵션을 무시하고 늘 0 을 돌려준다 → 모든 포트가 '사용 중' 이 되어 무한 반복했다.
    # 반환값 말고 출력에 그 포트가 실제로 있는지 본다.
    lsof -nP -iTCP:"$1" -sTCP:LISTEN -iUDP:"$1" 2>/dev/null | grep -E "[:.]$1( |\$)" >/dev/null && return 0
  fi
  return 1
}

step "설정 파일 (.env)"
[ -f .env.example ] || die ".env.example 이 없어요 — 올바른 폴더인지 확인하세요."
fresh=0
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fresh=1; ok ".env.example → .env 복사"; fi
if [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi
asks=""; q=""; new_keys=" "
while IFS= read -r line || [ -n "$line" ]; do  # .env.example 에 새로 생긴 항목 덧붙이기 + '# 묻기:' 질문 모으기
  case "$line" in
    '# 묻기:'*) q=$(printf '%s' "${line#"# 묻기:"}" | sed 's/^ *//'); continue ;;
    ''|'#'*) q=""; continue ;;
  esac
  key=${line%%=*}
  if [ -n "$q" ]; then asks="$asks$key|$q
"; q=""; fi
  if ! grep -q "^$key=" .env; then printf '%s\n' "$line" >> .env; new_keys="$new_keys$key "; ok "새 항목 $key"; fi
done < .env.example

keys=$(sed -n 's/^\([A-Za-z0-9_]*\)=.*/\1/p' .env)
used=" "
for key in $keys; do  # 이미 정해진 포트 — 새로 고를 때 피한다
  case "$key" in *_PORT) v=$(env_get "$key"); if [ -n "$v" ]; then used="$used$v "; fi ;; esac
done
next=18000
for key in $keys; do
  v=$(env_get "$key")
  case "$key" in
    *_PORT)
      # 빈 칸이거나, 방금 복사한 기본값이 이 PC 에서 이미 쓰이는 중이면 빈 포트를 고른다
      if [ -z "$v" ] || { [ $fresh = 1 ] && port_busy "$v"; }; then
        tries=0
        while port_busy "$next" || case "$used" in *" $next "*) true ;; *) false ;; esac; do
          next=$((next + 1)); tries=$((tries + 1))
          [ $tries -lt 2000 ] || die "빈 포트를 찾지 못했어요 (2000개가 모두 사용 중으로 보임) — 개발자에게 알려 주세요."
        done
        env_set "$key" "$next"; used="$used$next "; ok "$key=$next"; next=$((next + 1))
      fi ;;
    *_PASS|*_SECRET)
      if [ -z "$v" ]; then env_set "$key" "$(rand)"; ok "$key 자동 생성"; fi ;;
  esac
done

# 설치하는 사람만 아는 값 — .env.example 에서 바로 윗줄이 '# 묻기: <질문>' 인 칸. 짐작해서 채우지 않고 묻는다.
# 처음 설치할 때와 새로 생긴 칸만 (다시 실행할 때마다 묻지 않음). Enter = 비워 둠.
if [ -n "$asks" ]; then
  tty=0; if [ -t 0 ] && [ -r /dev/tty ]; then tty=1; fi
  # 참고용 이 PC 주소 — docker·가상 브리지(br-·docker0·veth·virbr·bridge)는 빼고
  ips=$(ip -4 -o addr show scope global 2>/dev/null | awk '$2 !~ /^(docker|br-|veth|virbr|bridge)/ {split($4, a, "/"); printf "%s(%s) ", a[1], $2}')
  [ -n "$ips" ] || ips=$(ifconfig 2>/dev/null | awk '/^[a-z]/{n=$1; sub(/:$/, "", n)} /inet / && $2 != "127.0.0.1" && n !~ /^(docker|br-|veth|virbr|bridge)/ {printf "%s(%s) ", $2, n}')
  while IFS='|' read -r key q; do
    [ -n "$key" ] || continue
    if [ -n "$(env_get "$key")" ]; then continue; fi
    case "$fresh$new_keys" in 1*|*" $key "*) ;; *) continue ;; esac
    if [ $tty = 0 ]; then warn "$key 비워 둠 (물어볼 화면 없음) — 필요하면 .env 에 직접 쓰고 다시 실행"; continue; fi
    printf '\n  ? %s\n' "$q"
    case "$key" in *_HOST|*_IP) if [ -n "$ips" ]; then printf '    참고 — 이 PC 의 IP: %s\n' "$ips"; fi ;; esac
    printf '  > '
    ans=""; read -r ans </dev/tty || ans=""
    ans=$(printf '%s' "$ans" | sed 's/^ *//; s/ *$//')
    if [ -n "$ans" ]; then env_set "$key" "$ans"; ok "$key=$ans"; else ok "$key 비워 둠"; fi
  done <<EOF
$asks
EOF
fi

chmod 600 .env  # 비밀번호가 들어 있다 — 나만 읽게 (전부터 있던 .env 도)

# ── 3. GPU ──
step "GPU 확인"
gpu=0
if [ -f docker-compose.gpu.yml ]; then
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep nvidia >/dev/null; then
      gpu=1; ok "NVIDIA GPU 사용"
    else
      warn "NVIDIA GPU 는 있지만 Docker 가 GPU 를 못 써요 → CPU 로 실행해요."
      warn "GPU 를 쓰려면 NVIDIA Container Toolkit 설치 후 다시 실행: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    fi
  else
    ok "GPU 없음 → CPU 로 실행 (느릴 수 있어요)"
  fi
else
  ok "이 프로그램은 GPU 를 쓰지 않아요"
fi
if [ $gpu = 1 ]; then
  env_set COMPOSE_PATH_SEPARATOR ":"
  env_set COMPOSE_FILE "docker-compose.yml:docker-compose.gpu.yml"
else
  env_del COMPOSE_FILE; env_del COMPOSE_PATH_SEPARATOR
fi

# ── 4. 모델 파일 ──
if [ -f weights.txt ]; then
  step "모델 파일 받기"
  command -v curl >/dev/null 2>&1 || die "curl 이 없어요. 설치한 뒤 다시 실행하세요."
  while read -r path url _ || [ -n "${path:-}" ]; do
    case "$path" in ''|'#'*) continue ;; esac
    if [ -s "$path" ]; then ok "$path (이미 있음)"; continue; fi
    mkdir -p "$(dirname "$path")"
    curl -fL --retry 3 -o "$path.part" "$url" || die "$path 를 받지 못했어요: $url"
    mv "$path.part" "$path"; ok "$path"
  done < weights.txt
fi

# ── 5. 받기·만들기·켜기 ──
step "설정 검사"
if ! out=$(docker compose config -q 2>&1); then
  die "설정이 덜 됐어요 — .env 를 열어 아래 항목을 채운 뒤 다시 실행하세요:
$out"
fi
ok "설정 정상"

step "프로그램 받기 (처음엔 몇 분 걸려요)"
pull=""; build=""
svcs=$(docker compose config | awk '/^services:/{s=1;next} /^[^ ]/{s=0}
  s&&/^  [^ ]/{v=$1;sub(/:$/,"",v);o[++n]=v} s&&/^    build:/{b[v]=1} s&&/^    image:/{i[v]=$2}
  END{for(k=1;k<=n;k++){v=o[k]; print v, (i[v]?i[v]:"-"), (b[v]?1:0)}}')
while read -r svc img b; do
  [ -n "$svc" ] || continue
  case "$img" in
    ghcr.io/*) pull="$pull $svc" ;;
    *) if [ "$b" = 1 ]; then build="$build $svc"; fi ;;
  esac
done <<EOF
$svcs
EOF
for svc in $pull; do
  if docker compose pull "$svc"; then ok "$svc 받음"
  else warn "$svc 이미지를 못 받았어요 → 이 PC 에서 직접 만들어요 (오래 걸려요)"; build="$build $svc"; fi
done
if [ -n "$build" ]; then
  step "이 PC 에서 만들기:$build"
  # shellcheck disable=SC2086
  docker compose build $build || die "만들기에 실패했어요. 위 오류를 개발자에게 보내 주세요."
fi

step "켜기 (다 켜질 때까지 기다려요)"
if ! docker compose up -d --wait --wait-timeout 900; then
  docker compose ps
  die "켜지지 않았어요. 'docker compose logs' 출력을 개발자에게 보내 주세요."
fi

port=$(env_get FRONTEND_PORT); [ -n "$port" ] || port=$(env_get BACKEND_PORT)
printf '\n✅ 설치 끝 — 브라우저에서 http://localhost:%s\n' "$port"
echo "   끄기: docker compose down   다시 켜기: docker compose up -d   업데이트: git pull 후 ./setup.sh"
