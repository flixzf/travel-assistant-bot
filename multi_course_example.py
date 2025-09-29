"""
다중 코스 예매 시스템 사용 예시
"""

import asyncio
import logging
from datetime import datetime
from pipeline import TargetRegistry

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def single_course_example():
    """단일 코스 예매 예시 (기존 방식)"""
    registry = TargetRegistry()
    chat_id = 12345

    # 단일 코스 추가 (바로 예매 모드)
    target = await registry.add_target(
        chat_id=chat_id,
        service="SRT",
        departure="수서",
        arrival="부산",
        date="2025-01-05",
        time="10:00",
        scan_only=False  # 바로 예매
    )

    logger.info("단일 코스 추가됨: %s", target.target_id)
    return registry


async def multi_course_example():
    """다중 코스 예매 예시"""
    registry = TargetRegistry()
    chat_id = 12345

    # 다중 코스 데이터 준비
    courses = [
        {
            "service": "SRT",
            "departure": "수서",
            "arrival": "부산",
            "date": "2025-01-05",
            "time": "08:00",
            "priority": 1,  # 최우선
            "scan_only": True  # 확인만
        },
        {
            "service": "SRT",
            "departure": "수서",
            "arrival": "부산",
            "date": "2025-01-05",
            "time": "09:00",
            "priority": 2,  # 두번째 우선순위
            "scan_only": True
        },
        {
            "service": "KTX",
            "departure": "서울",
            "arrival": "부산",
            "date": "2025-01-05",
            "time": "08:30",
            "priority": 3,  # 세번째 우선순위
            "scan_only": True
        }
    ]

    # 다중 코스 그룹으로 추가
    targets = await registry.add_target_group(
        chat_id=chat_id,
        targets_data=courses
    )

    group_id = targets[0].group_id
    logger.info("다중 코스 그룹 추가됨: %s (타겟 %d개)", group_id, len(targets))

    # 그룹 내 타겟들 확인
    group_targets = await registry.get_targets_by_group(chat_id, group_id)
    for target in group_targets:
        logger.info("- %s: %s %s->%s %s %s (우선순위: %d, 확인모드: %s)",
                   target.target_id, target.service, target.departure,
                   target.arrival, target.date, target.time,
                   target.priority, target.scan_only)

    return registry, group_id


async def mixed_targets_example():
    """단일 + 다중 코스 혼합 예시"""
    registry = TargetRegistry()
    chat_id = 12345

    # 단일 코스 1개 추가
    single_target = await registry.add_target(
        chat_id=chat_id,
        service="SRT",
        departure="동대구",
        arrival="서울",
        date="2025-01-06",
        time="15:00",
        scan_only=False
    )

    # 다중 코스 그룹 추가
    multi_courses = [
        {
            "service": "KTX",
            "departure": "서울",
            "arrival": "대전",
            "date": "2025-01-07",
            "time": "09:00",
            "priority": 1
        },
        {
            "service": "SRT",
            "departure": "수서",
            "arrival": "대전",
            "date": "2025-01-07",
            "time": "09:30",
            "priority": 2
        }
    ]

    multi_targets = await registry.add_target_group(
        chat_id=chat_id,
        targets_data=multi_courses
    )

    # 전체 타겟 확인
    all_targets = await registry.list_targets(chat_id)
    logger.info("총 %d개 타겟 (단일 1개, 다중 그룹 1개)", len(all_targets))

    # Rate 확인
    for target in all_targets:
        logger.info("타겟 %s: %.2f 회/분 (간격: %.2f초)",
                   target.target_id, target.rate_per_minute, target.scan_interval)

    return registry


async def simulate_ticket_found_scenario():
    """표 발견 시나리오 시뮬레이션"""
    registry = TargetRegistry()
    chat_id = 12345

    # 다중 코스 추가
    courses = [
        {
            "service": "SRT",
            "departure": "수서",
            "arrival": "부산",
            "date": "2025-01-05",
            "time": "08:00",
            "priority": 1
        },
        {
            "service": "SRT",
            "departure": "수서",
            "arrival": "부산",
            "date": "2025-01-05",
            "time": "10:00",
            "priority": 2
        }
    ]

    targets = await registry.add_target_group(chat_id, courses)
    group_id = targets[0].group_id

    logger.info("표 발견 전 상태:")
    for target in targets:
        logger.info("- %s: scan_only=%s, is_active=%s",
                   target.target_id, target.scan_only, target.is_active)

    # 표 발견 시뮬레이션 - 최우선 타겟 활성화
    best_target = await registry.activate_best_target_in_group(chat_id, group_id)

    logger.info("표 발견 후 상태 (활성화된 타겟: %s):", best_target.target_id)
    updated_targets = await registry.get_targets_by_group(chat_id, group_id)
    for target in updated_targets:
        logger.info("- %s: scan_only=%s, 우선순위=%d",
                   target.target_id, target.scan_only, target.priority)


async def main():
    """메인 실행 함수"""
    logger.info("=== 단일 코스 예시 ===")
    await single_course_example()

    logger.info("\n=== 다중 코스 예시 ===")
    await multi_course_example()

    logger.info("\n=== 혼합 타겟 예시 ===")
    await mixed_targets_example()

    logger.info("\n=== 표 발견 시나리오 ===")
    await simulate_ticket_found_scenario()


if __name__ == "__main__":
    asyncio.run(main())