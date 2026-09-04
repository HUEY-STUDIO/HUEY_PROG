"""터미널에서 파이프라인을 바로 확인하는 도구.

    python -m app.cli "서울특별시 강남구 테헤란로 152"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.services import pipeline
from app.utils.http import PublicApiError, close_client


async def _run(args: argparse.Namespace) -> int:
    try:
        report = await pipeline.analyze_address(
            args.address,
            candidate_index=args.index,
            with_statute_content=args.full_statutes,
            include_ordinances=not args.no_ordinances,
        )
    except pipeline.AddressNotFound as exc:
        print(f"주소를 찾지 못했습니다: {exc}", file=sys.stderr)
        return 1
    except PublicApiError as exc:
        print(f"외부 API 오류: {exc}", file=sys.stderr)
        return 2
    finally:
        await close_client()

    if args.json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    else:
        _print_human(report)
    return 0


def _print_human(report) -> None:
    o = report.overview
    print(f"입력       : {report.query}")
    print(f"도로명주소 : {report.address.road_address}")
    print(f"지번주소   : {report.address.jibun_address}")
    print(f"PNU        : {report.address.pnu}")
    if report.coordinate:
        print(f"좌표       : {report.coordinate.latitude}, {report.coordinate.longitude}")
    print()
    print("--- 대지개요 ---")
    print(f"지목       : {o.land_category or '-'}")
    print(f"대지면적   : {o.area_m2 if o.area_m2 is not None else '-'} m2")
    print(f"용도지역   : {o.primary_zone or '-'}")
    if o.designations:
        print("지역·지구  :")
        for d in o.designations:
            mark = " (저촉)" if d.conflict else ""
            print(f"  - {d.name}{mark}")
    print()

    if report.legal_limit:
        limit = report.legal_limit
        print("--- 법정 상한 (국토계획법 시행령) ---")
        print(f"건폐율 상한 : {limit.building_coverage_max_pct}%")
        print(
            f"용적률 범위 : {limit.floor_area_ratio_min_pct}% ~ "
            f"{limit.floor_area_ratio_max_pct}%"
        )
        if report.size_estimate:
            e = report.size_estimate
            print(f"건축면적 상한 : {e.max_building_area_m2} m2")
            print(f"연면적 상한   : {e.max_total_floor_area_m2} m2")
            print(f"참고 층수     : 약 {e.approx_max_floors}층")
        print(f"* {limit.note}")
        print()

    if report.ordinance_candidates:
        print("--- 조례 후보 (자동 판정 아님) ---")
        for hit in report.ordinance_candidates:
            print(f"  - {hit.title} ({hit.local_gov or '-'}) {hit.link or ''}")
        print()

    if report.warnings:
        print("--- 주의 ---")
        for warning in report.warnings:
            print(f"  ! {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="주소로 대지 법규를 조회합니다.")
    parser.add_argument("address", help="조회할 주소")
    parser.add_argument("--index", type=int, default=0, help="주소 후보 번호(0-base)")
    parser.add_argument("--json", action="store_true", help="JSON 원문 출력")
    parser.add_argument("--full-statutes", action="store_true", help="법령 조문 본문까지 조회")
    parser.add_argument("--no-ordinances", action="store_true", help="조례 검색 생략")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
