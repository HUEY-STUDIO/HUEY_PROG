# 연동 검증 현황

실제 공공 API 를 호출해 어디까지 확인됐는지 기록한다.
새 세션에서 작업을 이어갈 때 검증을 처음부터 반복하지 않기 위한 문서다.

최종 갱신: 2026-09-04 (2차 진단)

---

## 요약

| 단계 | API | 상태 |
|------|-----|------|
| 1 | 도로명주소 (주소 → PNU) | ✅ **실제 응답으로 검증 완료** |
| 1 | 브이월드 Geocoder (좌표) | ❌ **호출 지점 차단** — 서버가 응답 없이 연결을 끊음 |
| 2 | NSDI 토지이용계획 / 토지특성 | 🔧 **잘못된 엔드포인트 확인 → 코드 수정함**. 실응답 미검증(위와 같은 호스트) |
| 3 | 국가법령정보 (법령 조문) | ⚠️ 연결됨, **호출 서버 IP 등록 필요** |
| 4 | 자치법규 (조례 후보) | ⚠️ 위와 동일 (같은 API) |

**1차 진단 대비 달라진 점**: 네트워크 허용목록이 반영되어 `apis.data.go.kr`
`api.vworld.kr` 에 실제로 도달했다. 그 결과 '미검증'이던 2·3단계가
**네트워크 문제가 아니라 각각 다른 실제 원인**이었음이 드러났다.

---

## ✅ 검증 완료: 도로명주소 API

실제 응답을 받아 파서를 대조했고, 사용하는 필드명이 모두 실제와 일치한다.

**교차검증**: 조립한 PNU 가 응답의 `bdMgtSn`(건물관리번호) 앞 19자리와 일치.

```
입력   : 서울특별시 강남구 테헤란로 152
admCd  : 1168010100  lnbrMnnm: 737  lnbrSlno: 0  mtYn: 0
조립PNU: 1168010100107370000
bdMgtSn: 1168010100107370000023659   ← 앞 19자리 동일
```

**산(임야) 지번도 확인**:

```
제주특별자치도 서귀포시 중문동 산1-3 → 5013011200200010003
                                        └ 11번째 자리 '2' = 산, 본번 1, 부번 3
```

확인된 응답 필드: `roadAddr` `jibunAddr` `zipNo` `siNm` `sggNm` `emdNm`
`admCd` `lnbrMnnm` `lnbrSlno` `mtYn` (그 외 `bdNm` `rnMgtSn` `bdMgtSn` 등)

---

## 🔧 2단계: 엔드포인트가 틀렸었다 (수정 완료)

### 무엇이 틀렸나

기존 코드는 토지이용계획/토지특성을 **공공데이터포털**로 호출했다.

```
http://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr
http://apis.data.go.kr/1611000/nsdi/LandCharacteristicsService/attr/getLandCharacteristics
```

호출하면 HTTP 200 에 아래 본문이 실려 온다.

```json
{"OpenAPI_ServiceResponse": {"cmmMsgHeader": {
  "errMsg": "NO_OPENAPI_SERVICE_ERROR",
  "returnAuthMsg": "해당 오픈API 서비스가 없거나 폐기됨",
  "returnReasonCode": "12" }}}
```

### 어떻게 확정했나 — 오류코드로 경로/키를 구분하는 방법

공공데이터포털 게이트웨이는 **경로를 키보다 먼저 검사**한다. 이 성질을 쓰면
'경로가 틀린 것'과 '키가 미승인인 것'을 확실히 갈라낼 수 있다.

| 시험한 호출 | 결과 | 해석 |
|---|---|---|
| 존재하지 않는 가짜 경로 | 코드 **12** | 대조군 |
| 문제의 NSDI 경로 | 코드 **12** | 가짜 경로와 **구분되지 않음** |
| NSDI 경로 + 일부러 틀린 키 | 코드 **12** | 키보다 경로를 먼저 검사 |
| `1613000/BldRgstHubService/getBrTitleInfo` | 코드 **30** | 경로는 존재, 키만 미승인 |
| `1611000/BldRgstHubService/getBrTitleInfo` | 코드 **12** | 기관코드까지 포함해 정확히 매칭 |

즉 **코드 12 = 그런 경로 없음**, **코드 30 = 경로는 맞고 키가 미승인**.
NSDI 경로는 가짜 경로와 똑같이 12 를 냈으므로 경로 자체가 없는 것이다.
`nsdi` 세그먼트 제거·`getLandUseInfo` 등 변형 5종도 모두 12 였다.

### 올바른 호출 지점

이름은 국가공간정보포털이지만 실제로는 **브이월드 NED 게이트웨이**에서 서비스된다.
인증도 `serviceKey` 가 아니라 **`key` + `domain`** 이다.

```
https://api.vworld.kr/ned/data/getLandUseAttr
https://api.vworld.kr/ned/data/getLandCharacteristics
  ?key=<발급키>&domain=<등록도메인>&pnu=<19자리>&format=json&numOfRows=100&pageNo=1
```

### 코드에 반영한 것

- `app/config.py` — `nsdi_base_url` 을 `https://api.vworld.kr/ned/data` 로 변경.
  `nsdi_api_key`(미설정 시 `vworld_api_key` 로 대체), `nsdi_domain` 추가.
- `app/services/land_use.py` — 새 경로 + `key`/`domain` 인증. 요청 파라미터는
  `nsdi_params()` 한 곳으로 모아 doctor 와 서비스가 같은 요청을 보내게 했다.
- `tests/test_land_use.py` — 호출 호스트·경로·인증 파라미터를 고정하는
  회귀 테스트 2건 추가(옛 엔드포인트로 되돌리면 실패하는 것까지 확인).

> **아직 남은 것**: 응답 본문은 못 봤다(아래 브이월드 차단 때문).
> 파서(`extract_records`)는 특정 키에 의존하지 않는 구조라 그대로 동작할
> 가능성이 높지만, **실응답으로 필드명을 대조하는 일은 남아 있다.**
> 국내망에서 `python -m app.doctor --raw` 로 원본을 확보해 확인할 것.

---

## ❌ 브이월드(`api.vworld.kr`) — 이 환경에서 호출 지점이 막혀 있다

Geocoder 와 위 NED 토지 API 가 **같은 호스트**라 둘 다 여기서 막힌다.

### 증상

```
502 Bad Gateway — The server returned an invalid or incomplete response.
```

### 원인 — 인증키 문제가 아니다

단계별로 끊어 확인한 결과:

| 확인 항목 | 결과 |
|---|---|
| DNS | ✅ `211.188.33.95` 로 정상 해석 |
| 프록시 CONNECT 터널 | ✅ `200 Connection Established` (허용목록에 있음) |
| TLS 핸드셰이크 | ✅ 완료 — 진짜 인증서 확인 (GlobalSign, `*.vworld.kr`) |
| HTTP 요청 후 | ❌ **서버가 응답 없이 연결을 끊음** (`Empty reply from server`) |

즉 진짜 브이월드 서버까지 도달해 TLS 까지 맺은 뒤, 요청을 받고 그냥 끊는다.
중간 프록시가 이 빈 응답을 502 로 바꿔 전달할 뿐이다.

바꿔 가며 시험했지만 **전부 동일하게 실패**했다 — 브라우저 User-Agent,
`Referer` 추가, HTTP/1.0, 평문 HTTP(80), 다른 서비스 경로(`/req/search`,
`/ned/data`). 요청 내용과 무관하므로 **호출 지점(IP) 차단**으로 보인다.
브이월드가 해외/클라우드 IP 를 막는 사례와 증상이 일치한다.

> 참고: `www.vworld.kr` 은 허용목록에 아예 없어 CONNECT 가 403 으로 거절된다.
> `openapi.nsdi.go.kr` `www.nsdi.go.kr` 도 허용목록에 없다(DNS 해석 실패).
> 문서를 열어보려면 이 호스트들도 추가해야 한다.

**조치**: 코드로 풀 수 있는 문제가 아니다. **국내망(로컬 PC/국내 서버)에서
진단을 한 번 돌려** 이 가설을 확정하고, 동시에 NED 응답 구조를 확보하는 것이
가장 빠르다.

---

## ⚠️ 국가법령정보: 호출 서버 IP 등록 필요

네트워크는 연결되며 `LAW_OC` 도 형식상 맞다. 다만 API 가 HTTP 200 에
아래 본문을 실어 보낸다. (1차 진단과 동일, 변화 없음)

```json
{
  "result": "사용자 정보 검증에 실패하였습니다.",
  "msg": "OPEN API 호출 시 사용자 검증을 위하여 정확한 서버장비의 IP주소 및 도메인주소를 등록해 주세요."
}
```

**조치**: open.law.go.kr 의 OPEN API 신청 화면에서 **호출하는 서버의 IP/도메인**을
등록해야 한다. 클라우드 세션은 IP 가 매번 바뀌므로, 실제 배포할 서버의 IP 를
등록하는 것이 맞다.

이 응답 형태는 `app/services/law.py` 의 `raise_if_auth_error()` 가 감지해
실제 사유를 노출한다(그냥 두면 '결과 0건' 으로 보인다).

---

## 참고: 공공데이터포털 키 상태

`DATA_GO_KR_SERVICE_KEY` 는 이제 **건축물대장(건축HUB)에만** 쓰인다.
현재 이 키는 건축HUB 에 미승인 상태다(코드 30 확인). 건축물대장 연동을
진행하려면 활용신청이 필요하다.

---

## 네트워크 관련 메모

- 이 환경에는 `https_proxy` 만 설정되어 있고 `http_proxy` 는 없다.
  그래서 `http://` 호출은 프록시를 우회해 직접 나간다. 허용목록 동작이
  스킴에 따라 달라 보일 수 있으니 진단할 때 감안할 것.
- 허용된 호스트도 연결이 간헐적으로 끊기는 현상이 1차 진단에서 관측됐다
  (정상 응답 약 1초, 실패는 약 11.4초에 터널 끊김). 재시도 기본값은 3
  (`HTTP_MAX_RETRIES`).

---

## 새 세션에서 이어갈 때

1. **키 확인.** 이번 세션에서는 환경 대화상자의 `Environment variables` 에
   넣어 둔 값이 자동 주입됐다(`.env` 없이 동작). 비어 있으면 `.env` 를 만든다.

2. **진단부터 실행한다.**
   ```bash
   python -m app.doctor          # 단계별 통과/실패
   python -m app.doctor --raw    # 원본 응답 (파서 수정용)
   ```

3. **막힌 것부터 순서대로.** 남은 일은 코드가 아니라 대부분 신청·환경 쪽이다.
   - 브이월드: 국내망에서 재시험 → 되면 NED 응답 구조를 `--raw` 로 확보해
     `app/services/land_use.py` 파서 필드명을 대조.
   - 국가법령정보: open.law.go.kr 에 배포 서버 IP 등록.
   - 건축물대장: 공공데이터포털에서 건축HUB 활용신청.

4. 통과하면 실제 조회를 확인한다.
   ```bash
   python -m app.cli "서울특별시 강남구 테헤란로 152"
   ```
