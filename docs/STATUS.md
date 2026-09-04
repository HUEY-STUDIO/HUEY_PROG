# 연동 검증 현황

실제 공공 API 를 호출해 어디까지 확인됐는지 기록한다.
새 세션에서 작업을 이어갈 때 검증을 처음부터 반복하지 않기 위한 문서다.

최종 갱신: 2026-09-04

---

## 요약

| 단계 | API | 상태 |
|------|-----|------|
| 1 | 도로명주소 (주소 → PNU) | ✅ **실제 응답으로 검증 완료** |
| 1 | 브이월드 Geocoder (좌표) | ⏸ 미검증 — 네트워크 허용 대기 |
| 2 | 국가공간정보포털 (대지개요) | ⏸ 미검증 — 네트워크 허용 대기 |
| 3 | 국가법령정보 (법령 조문) | ⚠️ 연결됨, **호출 서버 IP 등록 필요** |
| 4 | 자치법규 (조례 후보) | ⚠️ 위와 동일 (같은 API) |

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

## ⏸ 미검증: 브이월드 / 국가공간정보포털

세션 네트워크 허용목록에 없어 호출하지 못했다. 게이트웨이 응답:

```
Host not in allowlist: apis.data.go.kr.
Add this host to your network egress settings to allow access.
```

**조치**: claude.ai/code 의 환경 선택기(메시지창 위 구름 아이콘) → 환경 톱니바퀴 →
`Network access` 를 `Custom` 으로 → `Allowed domains` 에 아래를 한 줄씩:

```
business.juso.go.kr
www.law.go.kr
api.vworld.kr
apis.data.go.kr
```

`Also include default list of common package managers` 는 켜 둔다.
**설정은 세션 시작 시점에만 읽히므로 저장 후 새 세션을 열어야 반영된다.**

### 특히 확인이 필요한 부분

`apis.data.go.kr` 의 **요청 경로가 공개 문서 기준 추정값**이다. 발급 후 받는
활용가이드와 대조해야 한다. 현재 기본값 (`app/config.py`, `.env` 로 교체 가능):

```
http://apis.data.go.kr/1611000/nsdi/LandUseService/attr/getLandUseAttr
http://apis.data.go.kr/1611000/nsdi/LandCharacteristicsService/attr/getLandCharacteristics
```

응답 구조가 예상과 다르면 `python -m app.doctor --raw` 로 원본을 확보해
`app/services/land_use.py` 의 파서를 수정한다.

---

## ⚠️ 국가법령정보: 호출 서버 IP 등록 필요

네트워크는 연결되며 `LAW_OC=ks683527` 도 형식상 맞다. 다만 API 가 HTTP 200 에
아래 본문을 실어 보낸다.

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

## 관측된 네트워크 특성

허용된 호스트도 연결이 간헐적으로 끊긴다. 실측:

- 정상 응답: **약 1초**
- 실패: **약 11.4초에 터널이 끊김** (일정한 시점)

타임아웃을 늘려도 소용없는 형태여서 재시도 기본값을 2 → 3 으로 올렸다
(`HTTP_MAX_RETRIES`). 로컬 환경에서는 이 현상이 없을 수 있다.

---

## 새 세션에서 이어갈 때

1. **키를 다시 넣어야 한다.** `.env` 는 `.gitignore` 에 있어 저장소에 없고,
   컨테이너는 세션마다 새로 만들어진다.
   → 매번 만들기 번거로우면 환경 대화상자의 **`Environment variables`** 칸에
   `.env` 형식으로 넣어두면 모든 세션에 자동 적용된다.
   (단, 그 환경을 쓰는 사람은 값을 볼 수 있다.)

2. **진단부터 실행한다.**
   ```bash
   python -m app.doctor          # 단계별 통과/실패
   python -m app.doctor --raw    # 원본 응답 (파서 수정용)
   ```

3. 통과하면 실제 조회를 확인한다.
   ```bash
   python -m app.cli "서울특별시 강남구 테헤란로 152"
   ```
