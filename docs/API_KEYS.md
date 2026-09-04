# 공공 API 서비스키 발급 및 .env 설정 가이드

이 프로젝트는 4개의 외부 서비스를 사용합니다. 각각 발급 주체와 절차가 다르며,
일부는 **승인까지 시간이 걸리므로** 개발 시작 전에 미리 신청해 두는 것이 좋습니다.

| # | 서비스 | 용도 | 발급처 | 소요 시간 | .env 키 |
|---|--------|------|--------|-----------|---------|
| 1 | 도로명주소 API | 주소 → 법정동코드·지번 (PNU) | business.juso.go.kr | 즉시(개발용) | devU01TX0FVVEgyMDI2MDkwNDE1MDQ0MjEyMDI1MDE= |
| 2 | 브이월드 | 주소 → 경위도 | api.vworld.kr | 즉시 | `VWORLD_API_KEY` |
| 3 | 공공데이터포털 | 토지이용계획·토지특성·건축물대장 | data.go.kr | 즉시(개발) / 1~2일(운영) | `DATA_GO_KR_SERVICE_KEY` |
| 4 | 국가법령정보 공동활용 | 법령·자치법규 조회 | open.law.go.kr | 1~2일 | `LAW_OC` |

---

## 1. 도로명주소 API (`JUSO_API_KEY`)

주소 검색 결과에서 **법정동코드(`admCd`), 본번(`lnbrMnnm`), 부번(`lnbrSlno`),
산 여부(`mtYn`)** 를 받아 19자리 PNU 를 조립합니다. 이 프로젝트에서 지번 변환의
기준이 되는 API 입니다.

1. https://business.juso.go.kr 접속 → 회원가입/로그인
2. `오픈API` → `신청하기` → **검색 API** 선택
3. 사용 환경에서 `개발용` 선택 (운영 전환은 서비스 오픈 시 별도 신청)
4. 발급된 **승인키(U0...)** 를 `.env` 의 `JUSO_API_KEY` 에 입력

> 개발용 승인키는 신청 즉시 발급되며 일 10,000건까지 호출할 수 있습니다.
> 운영용 키는 별도 심사를 거칩니다.

---

## 2. 브이월드 (`VWORLD_API_KEY`)

Geocoder API 2.0 으로 주소를 경위도(EPSG:4326)로 변환합니다.

1. https://www.vworld.kr 접속 → 회원가입/로그인
2. `오픈API` → `인증키 발급/관리` → **인증키 발급 신청**
3. 활용 API 에 **Geocoder API** 포함, 서비스 유형은 개발 단계에서 `서버 개발용` 선택
4. 발급된 인증키를 `.env` 의 `VWORLD_API_KEY` 에 입력

> **주의**: 지도 API 는 무료지만 **지오코더 API 는 일별 요청 건수 제한**이 있습니다.
> 트래픽이 늘면 브이월드에 초과 사용 신청을 해야 합니다. 이 프로젝트는 좌표 변환이
> 실패해도 나머지 결과는 정상 반환하도록 설계되어 있습니다.

---

## 3. 공공데이터포털 (`DATA_GO_KR_SERVICE_KEY`)

토지이용계획(용도지역/지구), 토지특성(지목·면적·공시지가), 건축물대장 조회에
공통으로 쓰입니다. 계정 하나의 인증키로 여러 API 를 활용신청해 사용합니다.

1. https://www.data.go.kr 접속 → 회원가입/로그인
2. 아래 API 를 각각 검색해 **활용신청**
   - 국토교통부 토지이용규제정보서비스 (LURIS)
     - https://www.data.go.kr/data/15057174/openapi.do
     - 개발계정 기준 **일 1,000건**
   - 국토교통부 토지특성정보 / 토지이용계획정보 (국가공간정보포털 NSDI 제공)
   - 국토교통부 건축HUB 건축물대장정보
     - https://www.hub.go.kr/portal/psg/idx-intro-openApi.do
3. `마이페이지` → `오픈API` → `인증키 발급현황` 에서 **일반 인증키** 확인
4. **Decoding 값**을 `.env` 의 `DATA_GO_KR_SERVICE_KEY` 에 입력

> ### 자주 겪는 함정
> - **Encoding / Decoding 키를 혼동하면 실패합니다.** 이 프로젝트는 `httpx` 가
>   쿼리스트링을 인코딩하므로 **Decoding 키**를 넣어야 합니다. Encoding 키를 넣으면
>   `+`, `=` 가 이중 인코딩되어 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 가 납니다.
> - 활용신청 직후에는 키가 반영되기까지 **최대 1시간** 걸릴 수 있습니다.
> - 개발계정은 일 호출 한도가 낮습니다. 이 프로젝트의 TTL 캐시
>   (`CACHE_TTL_SECONDS`)를 켜 두고 개발하세요.
> - 실서비스 전환 시 **운영계정 승인 절차**가 별도로 있습니다.

---

## 4. 국가법령정보 공동활용 (`LAW_OC`)

건축법·국토계획법 조문과 지자체 자치법규(조례)를 조회합니다.

1. https://open.law.go.kr 접속 → 회원가입/로그인
2. `OPEN API` → `OPEN API 신청` → 활용할 API 선택
   - **법령 목록/본문 조회**
   - **자치법규 목록/본문 조회**
3. 승인 후, `.env` 의 `LAW_OC` 에 **신청 시 등록한 이메일의 `@` 앞부분**을 입력
   - 예: `hong@gmail.com` 으로 신청했다면 `LAW_OC=hong`

> 다른 API 와 달리 별도의 긴 인증키가 아니라 **이메일 ID(`OC` 파라미터)** 를
> 사용합니다. 승인 전에 호출하면 오류가 나므로 승인 메일을 확인한 뒤 사용하세요.

---

## .env 설정

```bash
cp .env.example .env
# 편집기로 .env 를 열어 위에서 발급받은 값을 채웁니다.
```

설정이 제대로 됐는지는 서버를 띄우고 `/health` 로 확인합니다.

```bash
uvicorn app.main:app --reload
curl http://127.0.0.1:8000/health
```

```json
{ "status": "ok", "missing_keys": [], "cache_entries": 0 }
```

`missing_keys` 가 비어 있지 않으면 해당 단계는 동작하지 않습니다.
(예: `LAW_OC` 만 없으면 대지개요까지는 조회되고 조례 검색만 실패합니다.)

---

## 엔드포인트가 바뀐 경우

공공 API 는 운영 주체가 경로나 버전을 변경하는 경우가 있습니다.
모든 base URL 은 `.env` 로 덮어쓸 수 있으니, 활용가이드 문서와 다르면
코드를 고치지 말고 아래처럼 환경변수로 교체하세요.

```bash
NSDI_BASE_URL=http://apis.data.go.kr/1611000/nsdi
LAW_BASE_URL=https://www.law.go.kr/DRF
```

기본값은 `app/config.py` 의 `Settings` 에 정의되어 있습니다.
**각 API 의 정확한 요청 경로와 파라미터는 발급 후 받는 '활용가이드' PDF 를
반드시 대조 확인하세요.**
