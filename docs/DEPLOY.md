# 배포 가이드 (VPS + Docker)

이 문서는 `python -m app.doctor` / `python -m app.cli` 로 로컬 검증이 끝난
뒤, 실제 서비스로 올릴 때 쓰는 절차다. 배경(왜 로컬 PC 로는 안 되는지,
왜 고정 IP 가 필요한지)은 `docs/STATUS.md` 참고.

---

## 0. 사전 준비

- **VPS 1대** — 고정 공인 IP 가 있어야 한다 (Vultr, DigitalOcean, 가비아,
  카페24 등 아무 곳이나 무방). Ubuntu 22.04/24.04 기준으로 아래를 적었다.
- **Docker** 설치:
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # 재로그인 후 반영
  ```
- (선택) **도메인** — Cloudflare 등으로 이 VPS IP 를 가리키게 해둔다.

---

## 1. `.env` 준비 — 배포 전 체크리스트

로컬 `.env` 를 그대로 복사해 쓰면 안 된다. 아래 3가지는 **배포 서버 기준으로
다시 확인**해야 한다.

| 항목 | 확인할 것 |
|---|---|
| `DATA_GO_KR_SERVICE_KEY` | 공공데이터포털의 **일반 인증키(Decoding)** 값인지 확인. `%2B`/`%2F`/`%3D` 가 보이면 Encoding 값이니 포털에서 Decoding 값으로 다시 복사해온다. (`app/config.py` 가 Encoding 값을 자동으로 디코딩해주긴 하지만, 애초에 맞는 값을 쓰는 게 안전하다.) |
| `LAW_OC` | open.law.go.kr 의 OPEN API 신청 화면에서, **이 VPS 의 공인 IP** 를 호출 서버로 등록해야 한다. 로컬 PC IP(`106.240.12.84`)를 등록해봤자 배포 서버에서는 통과 못 한다. VPS 에서 `curl -s https://api.ipify.org` 로 실제 나가는 IP 를 확인해 등록한다. |
| `NSDI_DOMAIN` | 브이월드/NSDI 키 발급 시 등록한 도메인과 같아야 한다. 지금 `localhost` 로 되어 있다면, 실제 서비스 도메인으로 브이월드 포털에서 재등록이 필요할 수 있다. |

VPS 에 `.env` 파일을 옮겨 둔다(scp, 또는 직접 vi/nano 로 작성). **`.env` 는
git 에 커밋하지 않는다** — `.gitignore` 에 이미 포함되어 있다.

```bash
scp .env user@<VPS_IP>:/opt/huey-prog/.env
```

---

## 2. 코드 가져오기 + 빌드

```bash
git clone https://github.com/HUEY-STUDIO/HUEY_PROG.git /opt/huey-prog
cd /opt/huey-prog
# .env 를 여기 루트에 둔다 (위 scp 명령이 이미 이 경로에 둔 상태)

docker compose up -d --build
```

## 3. 확인

```bash
docker compose logs -f          # 시작 로그 확인 (Ctrl+C 로 빠져나옴)
curl -s http://localhost:8000/health
```

`{"status":"ok",...}` 가 나오면 정상이다. `"status":"degraded"` 면
`missing_keys` 에 뭐가 비었는지 나오니 `.env` 를 다시 확인한다.

실제 조회까지 확인하려면 컨테이너 안에서 진단 도구를 그대로 돌릴 수 있다:

```bash
docker compose exec api python -m app.doctor
```

---

## 4. (선택) Cloudflare 를 앞단에 세우기

VPS IP 를 직접 노출하지 않고, 무료 HTTPS·CDN·IP 은닉을 받으려면:

1. Cloudflare 에 도메인을 등록하고 A 레코드를 VPS IP 로 연결, **프록시(주황
   구름) 켜기**.
2. SSL/TLS 모드는 **Full (strict)** 권장. VPS 에 nginx 를 두고 Cloudflare
   Origin CA 인증서(Cloudflare 대시보드에서 무료 발급)를 물려 443 → 8000
   으로 리버스 프록시한다.

이 방식은 **인바운드(사용자→서버)** 경로만 Cloudflare 를 거친다.
**아웃바운드(서버→정부 API)** 호출은 여전히 VPS 의 고정 IP 로 나가므로,
법령정보 IP 등록에는 영향이 없다.

---

## 5. 배포 후 재확인

배포 서버가 바뀌거나 VPS 를 재발급받으면 IP 가 달라진다. 그러면 `[4]`
`[5]` 단계가 다시 실패하니, IP 를 다시 확인해서 open.law.go.kr 에 재등록
해야 한다.

```bash
curl -s https://api.ipify.org
```

---

## 참고: Docker 없이 직접 돌리는 방법

Docker 를 쓰기 어려운 환경이면 로컬에서 했던 것과 동일하게 venv 로도
돌아간다. 다만 재부팅 시 자동 재시작을 위해 systemd 유닛을 하나 만들어
두는 걸 권장한다.

```ini
# /etc/systemd/system/huey-prog.service
[Unit]
Description=HUEY_PROG API
After=network.target

[Service]
WorkingDirectory=/opt/huey-prog
EnvironmentFile=/opt/huey-prog/.env
ExecStart=/opt/huey-prog/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure
User=huey-prog

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now huey-prog
```
