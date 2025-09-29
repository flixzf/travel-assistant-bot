import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


@dataclass
class TargetItem:
    target_id: str
    chat_id: int
    service: str
    departure: str
    arrival: str
    date: str
    time: str
    user_limit: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    last_scan: Optional[datetime] = None
    last_success: Optional[datetime] = None
    next_scan: datetime = field(default_factory=lambda: datetime.utcnow())
    rate_per_minute: float = 0.0
    scan_interval: float = 60.0
    pending: bool = False
    cooldown_until: Optional[datetime] = None
    failure_count: int = 0
    # 다중 코스 지원을 위한 필드 추가
    group_id: Optional[str] = None  # 같은 그룹의 코스들을 식별
    priority: int = 1  # 우선순위 (낮을수록 높은 우선순위)
    scan_only: bool = False  # True면 확인만, False면 확인 후 예매


@dataclass
class ReservationTask:
    target: TargetItem
    train_payload: Dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.utcnow())


class TargetRegistry:
    def __init__(self) -> None:
        self._targets: Dict[int, Dict[str, TargetItem]] = defaultdict(dict)
        self._lock = asyncio.Lock()
        self._group_reservation_locks: Dict[str, asyncio.Lock] = {}  # 그룹별 예매 락
        self._group_reserved: Dict[str, bool] = {}  # 그룹별 예매 완료 상태
        self._logger = logging.getLogger(__name__ + ".TargetRegistry")

    async def add_target(
        self,
        chat_id: int,
        service: str,
        departure: str,
        arrival: str,
        date: str,
        time: str,
        user_limit: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        group_id: Optional[str] = None,
        priority: int = 1,
        scan_only: bool = False,
    ) -> TargetItem:
        target = TargetItem(
            target_id=str(uuid.uuid4())[:8],
            chat_id=chat_id,
            service=service.upper(),
            departure=departure,
            arrival=arrival,
            date=date,
            time=time,
            user_limit=user_limit,
            metadata=metadata or {},
            group_id=group_id,
            priority=priority,
            scan_only=scan_only,
        )
        async with self._lock:
            self._targets[chat_id][target.target_id] = target
            self._recompute_rates_locked(chat_id)
        self._logger.info("Target added %s for chat %s", target.target_id, chat_id)
        return target

    async def remove_target(self, chat_id: int, target_id: str) -> bool:
        async with self._lock:
            if target_id in self._targets.get(chat_id, {}):
                del self._targets[chat_id][target_id]
                self._recompute_rates_locked(chat_id)
                self._logger.info("Target %s removed for chat %s", target_id, chat_id)
                return True
        return False

    async def clear_targets(self, chat_id: int) -> int:
        async with self._lock:
            count = len(self._targets.get(chat_id, {}))
            if count:
                self._targets.pop(chat_id, None)
            return count

    async def list_targets(self, chat_id: int) -> List[TargetItem]:
        async with self._lock:
            return list(self._targets.get(chat_id, {}).values())

    async def add_target_group(
        self,
        chat_id: int,
        targets_data: List[Dict[str, Any]],
        group_id: Optional[str] = None,
    ) -> List[TargetItem]:
        """다중 코스를 그룹으로 추가"""
        if not group_id:
            group_id = str(uuid.uuid4())[:8]

        added_targets = []
        for i, target_data in enumerate(targets_data):
            target = await self.add_target(
                chat_id=chat_id,
                group_id=group_id,
                priority=target_data.get('priority', i + 1),
                scan_only=target_data.get('scan_only', True),  # 기본적으로 확인만
                **{k: v for k, v in target_data.items()
                   if k not in ['priority', 'scan_only', 'group_id']}
            )
            added_targets.append(target)

        self._logger.info("Target group %s added with %d targets for chat %s",
                         group_id, len(added_targets), chat_id)
        return added_targets

    async def get_targets_by_group(self, chat_id: int, group_id: str) -> List[TargetItem]:
        """그룹 ID로 타겟들 조회"""
        async with self._lock:
            targets = self._targets.get(chat_id, {}).values()
            return [t for t in targets if t.group_id == group_id]

    async def activate_best_target_in_group(self, chat_id: int, group_id: str) -> Optional[TargetItem]:
        """그룹 내에서 가장 우선순위가 높은 타겟을 예매 모드로 활성화"""
        async with self._lock:
            group_targets = [t for t in self._targets.get(chat_id, {}).values()
                           if t.group_id == group_id and t.is_active]
            if not group_targets:
                return None

            # 우선순위가 가장 높은(숫자가 낮은) 타겟 선택
            best_target = min(group_targets, key=lambda t: t.priority)

            # 모든 그룹 타겟을 scan_only=True로 설정
            for target in group_targets:
                target.scan_only = True

            # 선택된 타겟만 예매 모드로 설정
            best_target.scan_only = False

            self._logger.info("Activated target %s for reservation in group %s",
                            best_target.target_id, group_id)
            return best_target

    async def fetch_next_target(self) -> Optional[TargetItem]:
        now = datetime.utcnow()
        async with self._lock:
            candidate: Optional[TargetItem] = None
            for chat_targets in self._targets.values():
                for target in chat_targets.values():
                    if not target.is_active or target.pending:
                        continue
                    if target.cooldown_until and target.cooldown_until > now:
                        continue
                    if target.next_scan > now:
                        continue
                    if candidate is None or target.next_scan < candidate.next_scan:
                        candidate = target
            if candidate:
                candidate.last_scan = now
                candidate.next_scan = now + timedelta(seconds=candidate.scan_interval)
                return candidate
        return None

    async def set_pending(self, chat_id: int, target_id: str, pending: bool) -> None:
        async with self._lock:
            target = self._targets.get(chat_id, {}).get(target_id)
            if not target:
                return
            target.pending = pending
            if not pending:
                target.cooldown_until = None
            self._recompute_rates_locked(chat_id)

    async def mark_scan_failure(self, chat_id: int, target_id: str, backoff_seconds: float = 30.0) -> None:
        async with self._lock:
            target = self._targets.get(chat_id, {}).get(target_id)
            if not target:
                return
            target.failure_count += 1
            target.cooldown_until = datetime.utcnow() + timedelta(seconds=backoff_seconds)

    async def handle_reservation_result(self, chat_id: int, target_id: str, success: bool) -> None:
        async with self._lock:
            target = self._targets.get(chat_id, {}).get(target_id)
            if not target:
                return
            target.pending = False
            now = datetime.utcnow()
            if success:
                target.last_success = now
                target.is_active = False
                target.cooldown_until = now + timedelta(minutes=5)

                # 예매 성공 시 같은 그룹의 다른 타겟들도 모두 비활성화
                if target.group_id:
                    self._logger.info("Reservation success! Deactivating all targets in group %s", target.group_id)
                    deactivated_count = await self._deactivate_group_targets_locked(chat_id, target.group_id, exclude_target_id=target_id)
                    self._logger.info("Deactivated %d other targets in group %s", deactivated_count, target.group_id)
            else:
                target.failure_count += 1
                cooldown = min(120, 10 * target.failure_count)
                target.cooldown_until = now + timedelta(seconds=cooldown)
            self._recompute_rates_locked(chat_id)

    async def _deactivate_group_targets_locked(self, chat_id: int, group_id: str, exclude_target_id: Optional[str] = None) -> int:
        """그룹의 모든 타겟을 비활성화 (특정 타겟 제외 가능)"""
        deactivated_count = 0
        targets = self._targets.get(chat_id, {})

        for target in targets.values():
            if (target.group_id == group_id and
                target.target_id != exclude_target_id and
                target.is_active):
                target.is_active = False
                target.pending = False
                target.cooldown_until = datetime.utcnow() + timedelta(minutes=5)
                deactivated_count += 1
                self._logger.info("Deactivated target %s in group %s", target.target_id, group_id)

        return deactivated_count

    async def deactivate_group(self, chat_id: int, group_id: str) -> int:
        """그룹 전체 비활성화 (외부에서 호출 가능)"""
        async with self._lock:
            return await self._deactivate_group_targets_locked(chat_id, group_id)

    async def _get_group_lock(self, group_id: str) -> asyncio.Lock:
        """그룹별 락 가져오기 (없으면 생성)"""
        if group_id not in self._group_reservation_locks:
            self._group_reservation_locks[group_id] = asyncio.Lock()
        return self._group_reservation_locks[group_id]

    async def is_group_already_reserved(self, group_id: str) -> bool:
        """그룹이 이미 예매되었는지 확인"""
        return self._group_reserved.get(group_id, False)

    async def mark_group_reserved(self, group_id: str) -> None:
        """그룹을 예매 완료로 표시"""
        self._group_reserved[group_id] = True
        self._logger.info("Group %s marked as reserved", group_id)

    async def try_reserve_group(self, group_id: str) -> bool:
        """그룹 예매 시도 (이미 예매되었으면 False 반환)"""
        if await self.is_group_already_reserved(group_id):
            return False
        await self.mark_group_reserved(group_id)
        return True

    async def activate_target(self, chat_id: int, target_id: str) -> Optional[TargetItem]:
        async with self._lock:
            target = self._targets.get(chat_id, {}).get(target_id)
            if not target:
                return None
            target.is_active = True
            target.pending = False
            target.cooldown_until = None
            target.next_scan = datetime.utcnow()
            self._recompute_rates_locked(chat_id)
            return target

    def _recompute_rates_locked(self, chat_id: int) -> None:
        targets = self._targets.get(chat_id, {})
        active = [t for t in targets.values() if t.is_active]
        count = len(active)
        if not count:
            return

        # 안전율을 적용한 전체 제한: 95회/분
        total_limit = 95.0

        # 그룹별로 타겟을 분류하여 처리
        groups = defaultdict(list)
        individual_targets = []

        for target in active:
            if target.group_id:
                groups[target.group_id].append(target)
            else:
                individual_targets.append(target)

        # 전체 엔티티 수 계산 (그룹은 1개로 계산)
        total_entities = len(groups) + len(individual_targets)

        if total_entities == 0:
            return

        # 엔티티당 기본 할당량
        per_entity_rate = total_limit / total_entities
        now = datetime.utcnow()

        # 개별 타겟들 처리
        for target in individual_targets:
            user_limit = target.user_limit if target.user_limit and target.user_limit > 0 else total_limit
            target.rate_per_minute = min(per_entity_rate, user_limit)
            target.scan_interval = max(1.0, 60.0 / target.rate_per_minute) if target.rate_per_minute > 0 else 60.0
            if target.next_scan < now:
                target.next_scan = now

        # 그룹별 타겟들 처리
        for group_id, group_targets in groups.items():
            group_size = len(group_targets)
            # 그룹 내에서는 동등하게 분배
            per_target_in_group = per_entity_rate / group_size if group_size > 0 else per_entity_rate

            for target in group_targets:
                user_limit = target.user_limit if target.user_limit and target.user_limit > 0 else total_limit
                target.rate_per_minute = min(per_target_in_group, user_limit)
                target.scan_interval = max(1.0, 60.0 / target.rate_per_minute) if target.rate_per_minute > 0 else 60.0
                if target.next_scan < now:
                    target.next_scan = now

        self._logger.info("Rate recomputed for chat %s: %d groups, %d individual targets, %.2f rate per entity",
                         chat_id, len(groups), len(individual_targets), per_entity_rate)


class ScannerWorker:
    def __init__(
        self,
        registry: TargetRegistry,
        reservation_executor: 'ReservationExecutor',
        train_reservation,
    ) -> None:
        self.registry = registry
        self.reservation_executor = reservation_executor
        self.train_reservation = train_reservation
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._logger = logging.getLogger(__name__ + ".ScannerWorker")
        self.idle_sleep = 1.0

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = loop.create_task(self.run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                target = await self.registry.fetch_next_target()
                if not target:
                    await asyncio.sleep(self.idle_sleep)
                    continue
                train_payload = await self.train_reservation.scan_for_available_train(target)
                if not train_payload:
                    continue

                # scan_only 모드인 경우 표가 발견되면 같은 그룹의 최적 타겟을 예매 모드로 활성화
                if target.scan_only and target.group_id:
                    self._logger.info("Available train found in scan_only mode for target %s, checking group %s",
                                    target.target_id, target.group_id)

                    # 그룹별 락 획득
                    group_lock = await self.registry._get_group_lock(target.group_id)
                    async with group_lock:
                        # 이미 예매된 그룹인지 확인
                        if await self.registry.is_group_already_reserved(target.group_id):
                            self._logger.info("Group %s already reserved, skipping", target.group_id)
                            continue

                        # 그룹 예매 시도
                        if not await self.registry.try_reserve_group(target.group_id):
                            self._logger.info("Failed to reserve group %s, skipping", target.group_id)
                            continue

                        self._logger.info("Successfully reserved group %s, activating best target", target.group_id)
                        best_target = await self.registry.activate_best_target_in_group(
                            target.chat_id, target.group_id
                        )
                        if best_target:
                            # 최적 타겟으로 예매 진행
                            await self.registry.set_pending(best_target.chat_id, best_target.target_id, True)
                            await self.reservation_executor.enqueue(
                                ReservationTask(target=best_target, train_payload=train_payload)
                            )
                    continue

                # 일반 예매 모드 (scan_only=False 또는 단일 타겟)
                await self.registry.set_pending(target.chat_id, target.target_id, True)
                await self.reservation_executor.enqueue(
                    ReservationTask(target=target, train_payload=train_payload)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.exception("Scanner worker error: %s", exc)
                await asyncio.sleep(2.0)


class ReservationExecutor:
    def __init__(self, train_reservation, registry: TargetRegistry) -> None:
        self.train_reservation = train_reservation
        self.registry = registry
        self.queue: asyncio.Queue[ReservationTask] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.bot = None
        self._logger = logging.getLogger(__name__ + ".ReservationExecutor")

    def bind_bot(self, bot) -> None:
        self.bot = bot

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = loop.create_task(self.run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def enqueue(self, task: ReservationTask) -> None:
        await self.queue.put(task)

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                reservation_task = await self.queue.get()
                await self._process_task(reservation_task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.exception("Reservation executor error: %s", exc)

    async def _process_task(self, reservation_task: ReservationTask) -> None:
        target = reservation_task.target
        success = False
        try:
            success = await self.train_reservation.execute_auto_reservation(
                reservation_task, self.bot
            )

            # 예매 성공 시 그룹 정보와 함께 추가 알림
            if success and target.group_id and self.bot:
                try:
                    # 같은 그룹의 다른 타겟들 확인
                    group_targets = await self.registry.get_targets_by_group(target.chat_id, target.group_id)
                    other_active_count = sum(1 for t in group_targets
                                           if t.target_id != target.target_id and t.is_active)

                    if other_active_count > 0:
                        additional_msg = (
                            f"\n🛑 다중 모니터링 그룹 {target.group_id[:8]}...의 "
                            f"다른 {other_active_count}개 모니터링이 자동 중단되었습니다."
                        )
                        await self.bot.send_message(
                            chat_id=target.chat_id,
                            text=additional_msg
                        )
                except Exception as notify_err:
                    self._logger.debug("Failed to send group deactivation notification: %s", notify_err)

        except Exception as exc:
            self._logger.exception("Reservation task failed: %s", exc)
            if self.bot:
                try:
                    await self.bot.send_message(
                        chat_id=target.chat_id,
                        text=f"자동 예매 중 오류가 발생했습니다: {exc}"
                    )
                except Exception:
                    self._logger.debug("Failed to notify chat %s", target.chat_id)

            # 예매 실패 시 그룹 예매 상태 리셋
            if not success and target.group_id:
                # 그룹 예매 상태를 False로 리셋하여 다른 타겟이 시도할 수 있도록 함
                self.registry._group_reserved[target.group_id] = False
                self._logger.info("Reset group reservation status for group %s due to failure", target.group_id)

        finally:
            await self.registry.handle_reservation_result(target.chat_id, target.target_id, success)
            self.queue.task_done()
