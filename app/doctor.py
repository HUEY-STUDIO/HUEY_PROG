"""공공 API 연동 진단 도구.

4개 외부 서비스를 하나씩 호출해 어디까지 동작하는지 확인한다.
엔드포인트 경로나 응답 구조가 활용가이드와 다르면 여기서 바로 드러난다.

    python -m app.doctor
    python -m app.doctor --raw            # 원본 응답 전문 출력 (이슈 리포트용)
    python -m app.doctor --raw --raw-limit 0   # 잘라내지 않고 전부 출력
    python -m app.doctor --address "부산광역시 해운대구 우동 1394"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.config import get_settings
from app.domain.pnu import build_pnu
from app.services import geocode, land_use, law, ordinance
from app.utils import cache
from app.utils.http import PublicApiError, close_client, fetch

DEFAULT_ADDRESS = "서울특별시 강남구 테헤란로 152"

OK = "  [ OK ]"
FAIL = "  [FAIL]"
SKIP = "  [SKIP]"


class Doctor:
    # --raw 출력 시 항목당 기본 상한. 예전 4000자는 토지특성 응답조차
    # 중간에서 잘라 이슈 리포트로 쓸 수 없었다.
    DUMP_LIMIT = 20000

    def __init__(self, address: str, raw: bool, raw_limit: int = DUMP_LIMIT) -> None:
        self.address = address
        self.raw = raw
        self.raw_limit = raw_limit
        self.failures: list[str] = []
        self.pnu: str | None = None
        self.sido: str | None = None
        self.sigungu: str | None = None

    def _dump(self, label: str, payload: Any) -> None:
        if not self.raw:
            return
        if isinstance(payload, (dict, list)):
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            text = str(payload)

        print(f"\n--- {label} 원본 응답 ---")
        if self.raw_limit and len(text) > self.raw_limit:
            # 조용히 자르면 응답 구조가 잘린 건지 API 가 원래 그렇게 준 건지
            # 구분할 수 없다. 잘랐다는 사실을 반드시 남긴다.
            print(text[: self.raw_limit])
            print(
                f"... (출력이 잘렸습니다: 전체 {len(text)}자 중 앞 {self.raw_limit}자. "
                "전문을 보려면 --raw-limit 0)"
            )
        else:
            print(text)
        print("--- 끝 ---\n")

    NETWORK_HINT = (
        "상류 서버에 연결되지 않았습니다. 인증키가 아니라 네트워크 문제입니다. "
        "사내 프록시/방화벽, 또는 실행 환경의 아웃바운드 정책을 확인하세요."
    )

    def _fail(self, name: str, detail: str, hint: str = "") -> None:
        self.failures.append(name)
        print(f"{FAIL} {detail}")
        if hint:
            print(f"         → {hint}")

    def _fail_api(self, name: str, exc: PublicApiError, hint: str) -> None:
        """PublicApiError 를 원인에 맞는 힌트와 함께 보고한다."""
        self._fail(name, str(exc), self.NETWORK_HINT if exc.network else hint)
        # 원본이 가장 필요한 순간이 실패했을 때다. 상류에 닿기라도 했다면
        # 응답을 그대로 보여준다(네트워크 오류면 payload 가 None).
        if exc.payload is not None:
            self._dump(f"{name} 실패", exc.payload)

    # --- 0단계: 설정 ---------------------------------------------------
    def check_config(self) -> bool:
        print("\n[0] 설정 확인")
        settings = get_settings()
        missing = settings.missing_keys()
        if missing:
            self._fail(
                "config",
                f"설정되지 않은 키: {', '.join(missing)}",
                ".env 파일을 확인하세요 (docs/API_KEYS.md).",
            )
            return False
        key = settings.data_go_kr_service_key
        print(f"{OK} 인증키 4종 모두 설정됨")
        if "%" in key:
            print(
                "  [주의] 공공데이터포털 키에 '%' 가 남아 있습니다. "
                "Decoding 키인지 확인하세요."
            )
        return True

    # --- 1단계: 주소 -> PNU --------------------------------------------
    async def check_juso(self) -> bool:
        print(f"\n[1] 도로명주소 API — '{self.address}'")
        try:
            results = await geocode.search_addresses(self.address, limit=5)
        except PublicApiError as exc:
            self._fail_api(
                "juso",
                exc,
                "승인키가 '검색 API' 용인지, 개발용/운영용 구분이 맞는지 확인하세요.",
            )
            return False

        if not results:
            self._fail("juso", "검색 결과 0건", "다른 주소로 --address 를 지정해 보세요.")
            return False

        hit = results[0]
        self.pnu = hit.pnu
        self.sido = hit.sido
        self.sigungu = hit.sigungu
        print(f"{OK} {len(results)}건 검색")
        print(f"       도로명 : {hit.road_address}")
        print(f"       지번   : {hit.jibun_address}")
        print(f"       PNU    : {hit.pnu}")
        print(f"       지자체 : {hit.sido} {hit.sigungu}")

        # PNU 조립이 지번주소와 일치하는지 눈으로 확인할 수 있게 보여준다.
        expected = build_pnu(hit.ld_code, hit.main_no, hit.sub_no, mountain=hit.mountain)
        if expected != hit.pnu:
            self._fail("juso", f"PNU 조립 불일치: {expected} != {hit.pnu}")
            return False
        return True

    # 브이월드는 요청을 거절할 때 HTTP 오류 대신 TLS 연결만 맺고 응답 없이
    # 끊어버리는 경우가 있다. 그러면 중간 프록시가 502 로 바꿔 전달하므로
    # '인증키 문제' 로 오진하기 쉽다. 상태코드별로 사유를 갈라 안내한다.
    UPSTREAM_DROP_HINT = (
        "TLS 는 맺어졌지만 브이월드가 응답 없이 연결을 끊었습니다. "
        "인증키 문제가 아니라 호출 지점이 차단된 것으로 보입니다"
        "(브이월드는 해외/클라우드 IP 를 막는 사례가 있습니다). "
        "국내망에서 같은 요청이 되는지 먼저 확인하세요."
    )

    def _vworld_hint(self, exc: PublicApiError, otherwise: str) -> str:
        """브이월드 호스트 실패의 안내문.

        Geocoder 와 NSDI 토지 속성 API 는 같은 호스트(api.vworld.kr)라
        차단 증상도 같다. 5xx 면 키가 아니라 호출 지점 문제로 안내한다.
        """
        if exc.status_code in (502, 503, 504):
            return self.UPSTREAM_DROP_HINT
        return otherwise

    # --- 1단계: 좌표 ----------------------------------------------------
    async def check_vworld(self) -> bool:
        print("\n[2] 브이월드 Geocoder API")
        settings = get_settings()
        try:
            payload = await fetch(
                "vworld",
                settings.vworld_base_url,
                {
                    "service": "address",
                    "request": "getcoord",
                    "version": "2.0",
                    "crs": "epsg:4326",
                    "type": "road",
                    "address": self.address,
                    "refine": "true",
                    "simple": "false",
                    "format": "json",
                    "key": settings.vworld_api_key,
                },
            )
        except PublicApiError as exc:
            self._fail_api(
                "vworld",
                exc,
                self._vworld_hint(exc, "인증키 승인 상태와 사용 도메인 설정을 확인하세요."),
            )
            return False

        self._dump("브이월드", payload)
        status = (payload.get("response") or {}).get("status")
        if status != "OK":
            error = (payload.get("response") or {}).get("error")
            self._fail(
                "vworld",
                f"status={status} error={error}",
                "ERROR 면 인증키 문제, NOT_FOUND 면 주소 미매칭입니다. "
                "일 요청 한도 초과일 수도 있습니다.",
            )
            return False

        point = ((payload.get("response") or {}).get("result") or {}).get("point") or {}
        print(f"{OK} 좌표: {point.get('y')}, {point.get('x')}")
        return True

    # --- 2단계: 대지개요 ------------------------------------------------
    async def check_nsdi(self) -> bool:
        print("\n[3] 국가공간정보포털 — 토지이용계획 / 토지특성")
        if not self.pnu:
            print(f"{SKIP} PNU 가 없어 건너뜁니다 (1단계 실패).")
            return False

        settings = get_settings()
        ok = True

        for label, path, parser in (
            ("토지이용계획", "/getLandUseAttr", land_use.build_designations),
            ("토지특성", "/getLandCharacteristics", None),
        ):
            url = f"{settings.nsdi_base_url}{path}"
            try:
                payload = await fetch("nsdi", url, land_use.nsdi_params(settings, self.pnu))
            except PublicApiError as exc:
                ok = False
                self._fail(
                    f"nsdi-{label}",
                    f"{label}: {exc.detail}",
                    self.NETWORK_HINT
                    if exc.network
                    else self._vworld_hint(
                        exc,
                        "NSDI(국가공간정보포털)에서 이 API 의 활용신청이 승인됐는지, "
                        "그리고 NSDI_DOMAIN 이 키 발급 때 등록한 도메인과 같은지 "
                        f"확인하세요. 호출 URL: {url}",
                    ),
                )
                continue

            self._dump(label, payload)
            records = land_use.extract_records(payload)
            if not records:
                ok = False
                self._fail(
                    f"nsdi-{label}",
                    f"{label}: 응답은 왔으나 레코드를 찾지 못했습니다.",
                    "--raw 로 원본을 확인하세요. 응답 구조가 다르면 파서 수정이 필요합니다.",
                )
                continue

            print(f"{OK} {label}: {len(records)}건")
            if parser is not None:
                for d in parser(records):
                    mark = " (저촉)" if d.conflict else ""
                    zone = " ★용도지역" if d.is_use_district else ""
                    print(f"         - {d.name}{mark}{zone}")
            else:
                # 이 API 는 연도별 이력을 누적해 돌려준다(레코드 순서 보장 없음).
                # records[0] 을 그대로 쓰면 최신이 아닌 옛 연도 값을 보여줄 수
                # 있어(--raw 로 2013년 값이 잡히는 걸 확인) 최신 stdrYear 레코드를 고른다.
                latest = land_use.pick_latest_year(records)
                year = latest.get("stdrYear")
                note = f" (stdrYear={year}, 전체 {len(records)}건 중 최신)" if year else ""
                print(f"         기준연도{note}")
                for key in ("lndcgrCodeNm", "lndpclAr", "pblntfPclnd", "prposArea1Nm"):
                    if key in latest:
                        print(f"         {key} = {latest[key]}")
                print(f"         (필드 전체: {', '.join(sorted(latest))})")
        return ok

    # --- 3단계: 국가법령 ------------------------------------------------
    async def check_law(self) -> bool:
        print("\n[4] 국가법령정보 — 법령 목록 조회")
        try:
            records = await law.search_laws("건축법", display=3)
        except PublicApiError as exc:
            self._fail_api(
                "law",
                exc,
                "OC 값은 신청 시 등록한 이메일의 '@ 앞부분' 입니다. "
                "'사용자 정보 검증에 실패' 가 뜨면 open.law.go.kr 의 OPEN API "
                "신청 화면에서 호출하는 서버의 IP/도메인을 등록해야 합니다.",
            )
            return False

        if not records:
            self._fail(
                "law",
                "응답은 왔으나 결과가 비었습니다.",
                "--raw 로 원본을 확인하세요. OC 미승인 시 빈 응답이 오기도 합니다.",
            )
            return False

        print(f"{OK} {len(records)}건")
        for r in records[:3]:
            print(f"         - {r.get('법령명한글') or list(r.values())[:1]}")
        return True

    # --- 4단계: 자치법규 ------------------------------------------------
    async def check_ordinance(self) -> bool:
        print("\n[5] 자치법규 — 조례 후보 검색")
        if not self.sigungu and not self.sido:
            print(f"{SKIP} 지자체 정보가 없어 건너뜁니다 (1단계 실패).")
            return False

        hits, warnings = await ordinance.find_for_site(self.sido, self.sigungu)
        for w in warnings:
            print(f"  [주의] {w}")
        if not hits:
            await self._dump_ordinance_raw()
            self._fail(
                "ordin",
                "조례 후보 0건",
                "자치법규 API 활용신청이 승인됐는지 확인하세요.",
            )
            return False

        print(f"{OK} {len(hits)}건")
        for hit in hits[:5]:
            print(f"         - {hit.title} ({hit.local_gov or '-'})")
        return True

    async def _dump_ordinance_raw(self) -> None:
        """조례 검색 실패 시 대표 질의 1건의 원본 응답을 덤프한다.

        find_for_site() 는 개별 실패를 경고 문자열로 삼켜서 예외가 호출부까지
        올라오지 않는다. 같은 질의를 한 번 더 부르되 응답은 이미 캐시에 있어
        상류 호출이 추가로 나가지는 않는다.
        """
        if not self.raw:
            return
        region = self.sigungu or self.sido
        if not region:
            return
        query = f"{region} {ordinance.CORE_ORDINANCE_KINDS[0]}"
        try:
            await ordinance.search_ordinances(query)
        except PublicApiError as exc:
            if exc.payload is not None:
                self._dump(f"자치법규 '{query}'", exc.payload)

    async def run(self) -> int:
        print("=" * 64)
        print("공공 API 연동 진단")
        print("=" * 64)

        if not self.check_config():
            print("\n인증키가 없어 나머지 검사를 건너뜁니다.")
            return 1

        await self.check_juso()
        await self.check_vworld()
        await self.check_nsdi()
        await self.check_law()
        await self.check_ordinance()

        print("\n" + "=" * 64)
        if self.failures:
            print(f"실패 {len(self.failures)}건: {', '.join(self.failures)}")
            print("\n실패한 항목이 있으면 아래를 실행해 원본 응답을 확보하세요:")
            print(f'  python -m app.doctor --raw --address "{self.address}"')
            return 1
        print("전체 통과. 파이프라인이 정상 동작합니다.")
        print(f'  python -m app.cli "{self.address}"')
        return 0


async def _main(args: argparse.Namespace) -> int:
    cache.clear()
    doctor = Doctor(args.address, args.raw, args.raw_limit)
    try:
        return await doctor.run()
    finally:
        await close_client()


def main() -> int:
    parser = argparse.ArgumentParser(description="공공 API 연동 상태를 진단합니다.")
    parser.add_argument("--address", default=DEFAULT_ADDRESS, help="테스트에 사용할 주소")
    parser.add_argument("--raw", action="store_true", help="원본 응답 전문 출력")
    parser.add_argument(
        "--raw-limit",
        type=int,
        default=Doctor.DUMP_LIMIT,
        metavar="N",
        help=f"--raw 항목당 최대 출력 문자수 (기본 {Doctor.DUMP_LIMIT}, 0 이면 무제한)",
    )
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
