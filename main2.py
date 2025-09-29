import sys
import logging
import asyncio
import json
import os
import builtins
import calendar
from datetime import datetime, timedelta
from dotenv import load_dotenv  # 추가된 부분
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, CallbackQueryHandler

# letskorail 라이브러리 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'letskorail-master'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'SRT-2.6.7'))

from typing import Any, Dict, Optional
from letskorail.passenger import ChildPsg
from pipeline import TargetRegistry, ScannerWorker, ReservationExecutor, ReservationTask, TargetItem

from letskorail import Korail
from letskorail.options import AdultPsg, SeatOption
from SRT import SRT, SeatType
from functools import partial
from datetime import datetime
import subprocess
from SRT.passenger import Adult, Child




# 환경 변수 로드
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

# 보안 설정 로드
from secure_config import config_manager, validate_credentials, get_credential

# 로깅 설정
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# 크리덴셜 유효성 검사
if not validate_credentials():
    logger.error("필수 크리덴셜이 누락되었습니다. 환경변수를 확인해주세요.")
    sys.exit(1)

# 대화 상태 정의
DEPARTURE, DESTINATION, DATE, TIME, TRAIN_SERVICE = range(5)

# 달력 생성을 위한 상수
DAYS_OF_WEEK = ['월', '화', '수', '목', '금', '토', '일']
MONTHS = ['', '1월', '2월', '3월', '4월', '5월', '6월',
          '7월', '8월', '9월', '10월', '11월', '12월']


class SRTAutoPayment:
    def __init__(self, config=None):
        """
        SRT 결제 처리를 위한 핸들러 초기화

        Args:
            config (dict, optional): 결제 설정 정보를 담은 딕셔너리
                - payment_script_path: 결제 스크립트 경로
                - max_retries: 결제 재시도 횟수
                - retry_delay: 재시도 사이의 대기 시간(초)
        """
        # 기본 설정값 정의
        default_config = {
            'payment_script_path': 'srt_payment.py',
            'max_retries': 3,
            'retry_delay': 5
        }

        # 사용자 정의 설정과 기본 설정을 병합
        self.config = default_config
        if config:
            self.config.update(config)

        # 결제 스크립트 경로 확인
        self.payment_script_path = self.config['payment_script_path']
        if not os.path.exists(self.payment_script_path):
            raise FileNotFoundError(f"결제 스크립트를 찾을 수 없습니다: {self.payment_script_path}")

        # 결제 처리 상태 초기화
        self.current_transaction = None
        self.payment_status = None

        logger.info("SRTAutoPayment 핸들러 초기화 완료")

    async def process_payment(self, reservation_info, chat_id, context):
        """
        예약 정보를 기반으로 결제 프로세스 실행
        """
        logger.info(f"SRT 결제 프로세스 시작 - 예약번호: {reservation_info['reservation_number']}")

        self.current_transaction = {
            'reservation_id': reservation_info['reservation_number'],
            'train_info': reservation_info['train_info'],
            'start_time': datetime.now()
        }

        for attempt in range(self.config['max_retries']):
            try:
                env = os.environ.copy()
                env['SRT_RESERVATION_ID'] = reservation_info['reservation_number']

                logger.info(f"SRT 결제 시도 {attempt + 1}/{self.config['max_retries']}: "
                           f"예약번호 {reservation_info['reservation_number']}")
                logger.info(f"결제 스크립트 실행: {self.payment_script_path}")

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    self.payment_script_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env
                )

                logger.info("결제 스크립트 실행 중...")
                stdout, stderr = await process.communicate()
                logger.info(f"결제 스크립트 종료 코드: {process.returncode}")

                # 인코딩 처리 추가
                try:
                    stdout_str = stdout.decode('utf-8') if stdout else ''
                    stderr_str = stderr.decode('utf-8') if stderr else ''
                except UnicodeDecodeError:
                    # UTF-8 디코딩 실패시 CP949로 시도
                    stdout_str = stdout.decode('cp949', errors='ignore') if stdout else ''
                    stderr_str = stderr.decode('cp949', errors='ignore') if stderr else ''

                if stdout_str:
                    logger.info(f"결제 스크립트 출력: {stdout_str}")
                if stderr_str:
                    logger.warning(f"결제 스크립트 오류 출력: {stderr_str}")

                if process.returncode == 0:
                    logger.info(f"SRT 결제 성공 - 예약번호: {reservation_info['reservation_number']}")
                    await self._handle_payment_success(reservation_info, chat_id, context)
                    return True
                else:
                    error_msg = stderr_str
                    logger.error(f"SRT 결제 실패 (시도 {attempt + 1}): {error_msg}")

                    if attempt < self.config['max_retries'] - 1:
                        logger.warning(f"SRT 결제 실패, {self.config['retry_delay']}초 후 재시도")
                        await asyncio.sleep(self.config['retry_delay'])
                    else:
                        # 모든 시도 실패 후 재예약 프로세스 시작
                        failure_msg = (
                            f"❌ SRT 결제 실패\n"
                            f"예약번호: {reservation_info['reservation_number']}\n"
                            f"열차: {reservation_info['train_info']}\n"
                            f"오류: {error_msg}\n"
                            f"9분 45초 후 재예약을 시도합니다."
                        )
                        await context.bot.send_message(chat_id=chat_id, text=failure_msg)
                        logger.error(f"SRT 결제 최종 실패: {error_msg}")

                        # 실패한 예약 정보에서 원래 예약 정보 추출
                        train_info = reservation_info['train_info']
                        date_time = train_info.split()[0].replace('/', '') + train_info.split()[1].replace(':',
                                                                                                           '') + '00'
                        date = date_time[:8]
                        time = date_time[8:14]

                        # 9분 45초 대기 후 재예약 시도
                        logger.info("9분 45초 대기 후 재예약 시도")
                        await asyncio.sleep(585)  # 9분 45초 = 585초

                        # 재예약 시도
                        await context.bot.send_message(chat_id=chat_id, text="재예약을 시도합니다.")
                        train_reservation.search_and_reserve(
                            context.user_data['departure'],
                            context.user_data['destination'],
                            date,
                            time,
                            'SRT',
                            chat_id,
                            context
                        )
                        return False

            except Exception as e:
                logger.error(f"SRT 결제 프로세스 오류 (시도 {attempt + 1}): {str(e)}")
                if attempt == self.config['max_retries'] - 1:
                    error_msg = (
                        f"⚠️ SRT 결제 프로세스 오류\n"
                        f"예약번호: {reservation_info['reservation_number']}\n"
                        f"열차: {reservation_info['train_info']}\n"
                        f"오류: {str(e)}\n"
                        f"9분 45초 후 재예약을 시도합니다."
                    )
                    await context.bot.send_message(chat_id=chat_id, text=error_msg)

                    # 실패한 예약 정보에서 원래 예약 정보 추출
                    train_info = reservation_info['train_info']
                    date_time = train_info.split()[0].replace('/', '') + train_info.split()[1].replace(':', '') + '00'
                    date = date_time[:8]
                    time = date_time[8:14]

                    # 9분 45초 대기 후 재예약 시도
                    logger.info("9분 45초 대기 후 재예약 시도 (오류)")
                    await asyncio.sleep(585)  # 9분 45초 = 585초

                    # 재예약 시도
                    await context.bot.send_message(chat_id=chat_id, text="재예약을 시도합니다.")
                    train_reservation.search_and_reserve(
                        context.user_data['departure'],
                        context.user_data['destination'],
                        date,
                        time,
                        'SRT',
                        chat_id,
                        context
                    )
                    return False

    async def _handle_payment_success(self, reservation_info, chat_id, context):
        """결제 성공 처리"""
        success_msg = (
            f"🎉 SRT 예약 및 결제 완료!\n"
            f"예약번호: {reservation_info['reservation_number']}\n"
            f"열차: {reservation_info['train_info']}\n"
            f"결제 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await context.bot.send_message(chat_id=chat_id, text=success_msg)
        logger.info(f"SRT 결제 성공: {reservation_info['reservation_number']}")
        self.payment_status = 'SUCCESS'

class KorailAutoPayment:
    def __init__(self):
        self.payment_script_path = "korail_payment.py"

    async def process_payment(self, reservation_info, chat_id, context):
        """예약 성공 후 결제 처리 및 알림 전송"""
        logger.info(f"코레일 결제 프로세스 시작 - 예약번호: {reservation_info['rsv_no']}")

        try:
            # 환경변수 설정
            env = os.environ.copy()
            env['KORAIL_RESERVATION_ID'] = reservation_info['rsv_no']
            logger.info(f"결제 스크립트 실행 준비: {self.payment_script_path}")

            # 프로세스 생성 (encoding 파라미터 제거)
            process = await asyncio.create_subprocess_exec(
                sys.executable,  # python 실행 파일 경로
                self.payment_script_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )

            logger.info("코레일 결제 스크립트 실행 중...")
            # 프로세스 출력 처리
            stdout_data, stderr_data = await process.communicate()
            logger.info(f"결제 스크립트 종료 코드: {process.returncode}")

            # 바이트 데이터를 문자열로 디코딩
            try:
                stdout = stdout_data.decode('utf-8') if stdout_data else ''
                stderr = stderr_data.decode('utf-8') if stderr_data else ''
            except UnicodeDecodeError:
                # UTF-8 디코딩 실패시 CP949로 시도
                stdout = stdout_data.decode('cp949', errors='ignore') if stdout_data else ''
                stderr = stderr_data.decode('cp949', errors='ignore') if stderr_data else ''

            if stdout:
                logger.info(f"결제 스크립트 출력: {stdout}")
            if stderr:
                logger.warning(f"결제 스크립트 오류 출력: {stderr}")

            if process.returncode == 0:
                success_msg = (
                    f"🎉 예약 및 결제 완료!\n"
                    f"예약번호: {reservation_info['rsv_no']}\n"
                    f"열차: {reservation_info['train_info']}\n"
                    f"결제 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await context.bot.send_message(chat_id=chat_id, text=success_msg)
                logger.info(f"코레일 결제 성공: {reservation_info['rsv_no']}")
                return True

            else:
                error_msg = (
                    f"❌ 결제 실패\n"
                    f"예약번호: {reservation_info['rsv_no']}\n"
                    f"열차: {reservation_info['train_info']}\n"
                    f"오류: {stderr}\n"
                    f"9분 45초 후 재예약을 시도합니다."
                )
                await context.bot.send_message(chat_id=chat_id, text=error_msg)
                logger.error(f"코레일 결제 실패: {stderr}")

                # 재예약 로직 추가 필요시 여기에 구현

        except Exception as e:
            logger.error(f"코레일 결제 프로세스 오류: {str(e)}")
            # 에러 메시지 길이 제한 (텔레그램 메시지 길이 제한 대응)
            error_str = str(e)
            if len(error_str) > 500:
                error_str = error_str[:500] + "..."

            error_msg = (
                f"⚠️ 결제 프로세스 오류\n"
                f"예약번호: {reservation_info['rsv_no']}\n"
                f"열차: {reservation_info['train_info']}\n"
                f"오류: {error_str}\n"
                f"9분 45초 후 재예약을 시도합니다."
            )
            await context.bot.send_message(chat_id=chat_id, text=error_msg)

            # 재예약 로직 추가 필요시 여기에 구현

class StatusManager:
    def __init__(self, status_file="reservation_status.json"):
        self.status_file = status_file
        self.current_status = None  # 메모리상의 상태
        self.stop_event = asyncio.Event()  # 중단 이벤트 생성
        self.initialize_status()

    def initialize_status(self):
        """상태 초기화"""
        self.current_status = {
            'is_running': False,
            'should_stop': False,
            'chat_id': None,
            'last_check': datetime.now().isoformat()
        }
        self.stop_event.clear()  # 중단 이벤트 초기화
        self._save_status(self.current_status)

    def _save_status(self, status):
        """상태 파일 저장"""
        self.current_status = status
        with builtins.open(self.status_file, 'w') as f:
            json.dump(status, f)

    def _load_status(self):
        """상태 파일 로드"""
        if not self.current_status:
            if os.path.exists(self.status_file):
                with builtins.open(self.status_file, 'r') as f:
                    self.current_status = json.load(f)
            else:
                self.initialize_status()
        return self.current_status

    def start_reservation(self, chat_id):
        """예약 시작"""
        self.current_status = {
            'is_running': True,
            'should_stop': False,
            'chat_id': chat_id,
            'last_check': datetime.now().isoformat()
        }
        self.stop_event.clear()  # 중단 이벤트 초기화
        self._save_status(self.current_status)
        logger.info(f"예약 시작 - chat_id: {chat_id}")

    def stop_reservation(self, chat_id):
        """예약 중단"""
        status = self._load_status()
        if status and str(status['chat_id']) == str(chat_id):
            status['should_stop'] = True
            self.stop_event.set()  # 중단 이벤트 설정
            self._save_status(status)
            logger.info(f"예약 중단 요청 - chat_id: {chat_id}")
            return True
        return False

    def should_stop(self, chat_id):
        """중단 상태 확인"""
        status = self._load_status()
        return status and str(status['chat_id']) == str(chat_id) and status['should_stop']

    def cleanup(self):
        """상태 정리"""
        try:
            self.initialize_status()
            logger.info("상태 초기화 완료")
        except Exception as e:
            logger.error(f"상태 초기화 중 오류 발생: {e}")

class TrainReservation:
    def __init__(self):
        korail_user = get_credential('KORAIL_USER')
        korail_pass = get_credential('KORAIL_PASS')
        srt_user = get_credential('SRT_ID')  # SRT_ID 사용
        srt_pass = get_credential('SRT_PWD')

        logger.info(f"초기화 시작 - SRT User: {srt_user}, Korail User: {korail_user}")

        if not all([korail_user, korail_pass, srt_user, srt_pass]):
            logger.error("환경 변수가 설정되지 않았습니다.")
            logger.error(f"KORAIL_USER: {'✓' if korail_user else '✗'}")
            logger.error(f"KORAIL_PASS: {'✓' if korail_pass else '✗'}")
            logger.error(f"SRT_ID: {'✓' if srt_user else '✗'}")
            logger.error(f"SRT_PWD: {'✓' if srt_pass else '✗'}")
            sys.exit(1)

        # Korail 로그인 처리
        logger.info("Korail 로그인 시도 중...")
        try:
            self.korail = Korail()  # letskorail.Korail 사용
            login_result = self.korail.login(korail_user.strip(), korail_pass.strip())
            if login_result:
                logger.info("✓ Korail 로그인 성공")
            else:
                logger.error("✗ Korail 로그인 실패")
                sys.exit(1)
        except Exception as e:
            logger.error(f"✗ Korail 로그인 중 예외 발생: {str(e)}")
            sys.exit(1)

        # SRT 로그인 처리
        logger.info("SRT 로그인 시도 중...")
        try:
            self.srt = SRT(srt_user.strip(), srt_pass.strip())
            self.srt.login()
            logger.info("✓ SRT 로그인 성공")
        except Exception as e:
            logger.error(f"✗ SRT 로그인 실패: {str(e)}")
            sys.exit(1)

        self.RATE_LIMIT_DELAY = 1.0
        self.ATTEMPTS_PER_CYCLE = 10
        self.status_manager = StatusManager()
        self.reservation_task = None
        self.target_registry: Optional[TargetRegistry] = None
        self.scanner_worker: Optional[ScannerWorker] = None
        self.reservation_executor: Optional[ReservationExecutor] = None
        self.bot = None

        logger.info("TrainReservation 초기화 완료")

    def check_login_status(self):
        """로그인 상태 확인"""
        try:
            # Korail 로그인 상태 확인 (간단한 API 호출로 테스트)
            korail_status = self.korail is not None

            # SRT 로그인 상태 확인
            srt_status = self.srt is not None

            logger.info(f"로그인 상태 확인 - Korail: {'✓' if korail_status else '✗'}, SRT: {'✓' if srt_status else '✗'}")
            return korail_status and srt_status
        except Exception as e:
            logger.error(f"로그인 상태 확인 중 오류: {str(e)}")
            return False


    def attach_pipeline(self, target_registry: TargetRegistry, scanner_worker: ScannerWorker, reservation_executor: ReservationExecutor) -> None:
        self.target_registry = target_registry
        self.scanner_worker = scanner_worker
        self.reservation_executor = reservation_executor

    def bind_bot(self, bot) -> None:
        self.bot = bot

    async def scan_for_available_train(self, target: TargetItem) -> Optional[Dict[str, Any]]:
        service = (target.service or '').upper()
        if service == 'KTX':
            return await self._scan_available_ktx(target)
        if service == 'SRT':
            return await self._scan_available_srt(target)
        logger.warning("지원하지 않는 열차 서비스: %s", target.service)
        return None

    async def _scan_available_ktx(self, target: TargetItem) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            trains = await loop.run_in_executor(
                None,
                partial(
                    self.korail.search_train,
                    target.departure,
                    target.arrival,
                    target.date,
                    target.time,
                    include_soldout=False
                )
            )
        except Exception as exc:
            logger.debug("KTX 조회 실패(%s): %s", target.target_id, exc)
            if self.target_registry:
                await self.target_registry.mark_scan_failure(target.chat_id, target.target_id)
            return None

        available = list(trains) if trains else []
        if not available:
            return None

        train = available[0]
        summary = (
            f"{target.date[:4]}/{target.date[4:6]}/{target.date[6:]} "
            f"{train.dpt_time[:2]}:{train.dpt_time[2:4]} → {train.arv_time[:2]}:{train.arv_time[2:4]} "
            f"KTX {train.train_no}"
        )
        label = target.metadata.get('label')
        if label:
            summary = f"[{label}] {summary}"
        return {
            'service': 'KTX',
            'train': train,
            'summary': summary,
        }

    async def _scan_available_srt(self, target: TargetItem) -> Optional[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        try:
            trains = await loop.run_in_executor(
                None,
                partial(
                    self.srt.search_train,
                    target.departure,
                    target.arrival,
                    target.date,
                    target.time,
                    available_only=True
                )
            )
        except Exception as exc:
            logger.debug("SRT 조회 실패(%s): %s", target.target_id, exc)
            if self.target_registry:
                await self.target_registry.mark_scan_failure(target.chat_id, target.target_id)
            return None

        available = list(trains) if trains else []
        if not available:
            return None

        train = available[0]
        dep_time = train.dep_time.strftime('%H:%M')
        arr_time = train.arr_time.strftime('%H:%M')
        summary = (
            f"{target.date[:4]}/{target.date[4:6]}/{target.date[6:]} "
            f"{dep_time} → {arr_time} SRT {train.train_number}"
        )
        label = target.metadata.get('label')
        if label:
            summary = f"[{label}] {summary}"
        return {
            'service': 'SRT',
            'train': train,
            'summary': summary,
        }

    async def execute_auto_reservation(self, reservation_task: ReservationTask, bot) -> bool:
        target = reservation_task.target
        payload = reservation_task.train_payload
        service = (target.service or '').upper()
        if service == 'KTX':
            return await self._execute_auto_reservation_ktx(target, payload, bot)
        if service == 'SRT':
            return await self._execute_auto_reservation_srt(target, payload, bot)
        logger.warning("지원하지 않는 서비스로 예매 시도: %s", target.service)
        return False

    async def _execute_auto_reservation_ktx(self, target: TargetItem, payload: Dict[str, Any], bot) -> bool:
        train = payload.get('train')
        if train is None:
            return False

        seat_pref = str(target.metadata.get('seat', 'GENERAL_FIRST')).upper()
        seat_option_map = {
            'SPECIAL': SeatOption.SPECIAL_FIRST,
            'SPECIAL_ONLY': SeatOption.SPECIAL_ONLY,
            'GENERAL_ONLY': SeatOption.GENERAL_ONLY,
            'GENERAL_FIRST': SeatOption.GENERAL_FIRST,
        }
        seat_option = seat_option_map.get(seat_pref, SeatOption.GENERAL_FIRST)

        loop = asyncio.get_event_loop()
        try:
            reservation = await loop.run_in_executor(
                None,
                partial(self.korail.reserve, train, seat_opt=seat_option)
            )
            if reservation:
                reservation_id = getattr(reservation, 'rsv_no', None) or getattr(reservation, 'pnr_no', None) or '확인 필요'
                summary = payload.get('summary', '')
                message = (
                    "✅ KTX 자동 예매 성공\n"
                    f"{summary}\n"
                    f"예약번호: {reservation_id}"
                )
                if bot:
                    await bot.send_message(chat_id=target.chat_id, text=message)
                return True
        except Exception as exc:
            logger.warning("KTX 자동 예매 실패(%s): %s", target.target_id, exc)
            if bot:
                try:
                    await bot.send_message(chat_id=target.chat_id, text=f"KTX 자동 예매 실패: {exc}")
                except Exception:
                    logger.debug("KTX 실패 알림 전송 실패 - chat %s", target.chat_id)
        return False

    async def _execute_auto_reservation_srt(self, target: TargetItem, payload: Dict[str, Any], bot) -> bool:
        train = payload.get('train')
        if train is None:
            return False

        adult_count = int(target.metadata.get('adult_count', 1) or 0)
        child_count = int(target.metadata.get('child_count', 0) or 0)
        passengers = []
        if adult_count > 0:
            passengers.append(Adult(count=adult_count))
        if child_count > 0:
            passengers.append(Child(count=child_count))

        seat_pref = str(target.metadata.get('seat', 'GENERAL_FIRST')).upper()
        seat_map = {
            'SPECIAL': SeatType.SPECIAL_FIRST,
            'SPECIAL_ONLY': SeatType.SPECIAL_ONLY,
            'GENERAL_ONLY': SeatType.GENERAL_ONLY,
            'GENERAL_FIRST': SeatType.GENERAL_FIRST,
        }
        seat_type = seat_map.get(seat_pref, SeatType.GENERAL_FIRST)
        window_pref = bool(target.metadata.get('window_seat', False))

        loop = asyncio.get_event_loop()
        try:
            reservation = await loop.run_in_executor(
                None,
                partial(
                    self.srt.reserve,
                    train,
                    passengers=passengers or None,
                    special_seat=seat_type,
                    window_seat=window_pref
                )
            )
            if reservation:
                reservation_id = getattr(reservation, 'reservation_number', None)
                summary = payload.get('summary', '')
                message = (
                    "✅ SRT 자동 예매 성공\n"
                    f"{summary}\n"
                    f"예약번호: {reservation_id or '확인 필요'}"
                )
                if bot:
                    await bot.send_message(chat_id=target.chat_id, text=message)
                return True
        except Exception as exc:
            logger.warning("SRT 자동 예매 실패(%s): %s", target.target_id, exc)
            if bot:
                try:
                    await bot.send_message(chat_id=target.chat_id, text=f"SRT 자동 예매 실패: {exc}")
                except Exception:
                    logger.debug("SRT 실패 알림 전송 실패 - chat %s", target.chat_id)
        return False
    def search_and_reserve(self, dep, arr, date, time, service, chat_id, context):
        """예약 프로세스 시작"""
        self.status_manager.start_reservation(chat_id)
        loop = asyncio.get_event_loop()
        self.reservation_task = loop.create_task(
            self._reserve_process(dep, arr, date, time, service, chat_id, context)
        )

    async def _reserve_process(self, dep, arr, date, time, service, chat_id, context):
        try:
            if service == 'KTX':
                return await self.reserve_ktx(dep, arr, date, time, chat_id, context)
            elif service == 'SRT':
                return await self.reserve_srt(dep, arr, date, time, chat_id, context)
            else:
                return "잘못된 열차 서비스 선택입니다."
        except asyncio.CancelledError:
            logger.info("예약 프로세스가 취소되었습니다.")
            await context.bot.send_message(chat_id=chat_id, text="예약 프로세스가 취소되었습니다.")
            raise
        finally:
            self.status_manager.cleanup()

    def stop_reservation_task(self):
        if self.reservation_task:
            self.reservation_task.cancel()
            self.reservation_task = None

    async def reserve_ktx(self, dep, arr, date, time, chat_id, context):
        total_attempt_count = 0
        loop = asyncio.get_event_loop()

        while not self.status_manager.stop_event.is_set():
            for _ in range(self.ATTEMPTS_PER_CYCLE):
                if self.status_manager.stop_event.is_set():
                    logger.info("KTX 예약 중단 요청 감지")
                    return "사용자 요청으로 예약이 중단되었습니다."

                total_attempt_count += 1

                # 500회마다 로그인 상태 체크 및 재로그인 (약 8-10분마다)
                if total_attempt_count % 500 == 0:
                    logger.info(f"KTX 500회 도달, 정기 재로그인 진행 (시도 #{total_attempt_count})")
                    try:
                        korail_user = os.environ.get('KORAIL_USER')
                        korail_pass = os.environ.get('KORAIL_PASS')
                        self.korail = Korail()
                        self.korail.login(korail_user.strip(), korail_pass.strip())
                        logger.info("KTX 정기 재로그인 완료")
                        await asyncio.sleep(2.0)
                    except Exception as login_err:
                        logger.error(f"KTX 정기 재로그인 실패: {str(login_err)}")
                        await asyncio.sleep(5.0)

                try:
                    # 열차 검색 (모든 열차 검색)
                    trains = await loop.run_in_executor(None, partial(
                        self.korail.search_train,
                        dep, arr, date, time,
                        include_no_seats=True  # 잔여석 없는 열차도 포함
                    ))
                    
                    if not trains:
                        logger.warning(f"검색된 열차 없음")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="검색된 열차가 없습니다."
                        )
                        return False
                    
                    # 첫번째 열차 선택 (시간순 정렬되어 있음)
                    train = trains[0]
                    train_info = (f"{date[:4]}/{date[4:6]}/{date[6:]} "
                                  f"{train.dpt_time[:2]}:{train.dpt_time[2:4]} "
                                  f"KTX {train.train_no}번 열차")
                    
                    # 예약 시도
                    try:
                        adult_count = context.user_data.get('adult_count', 1)
                        child_count = context.user_data.get('child_count', 0)
                        window_seat = context.user_data.get('window_seat', False)
                        seat_type = context.user_data.get('seat_type', SeatType.GENERAL_FIRST)

                        passengers = []
                        if adult_count > 0:
                            passengers.append(AdultPsg(adult_count))
                        if child_count > 0:
                            passengers.append(AdultPsg(child_count))

                        # 창가 좌석 선택 로직
                        window_only = context.user_data.get('window_only', False)
                        seat_opt = SeatOption.GENERAL_FIRST  # 기본값

                        if window_seat:
                            # 창가 좌석 선택 시도
                            try:
                                selected_seats = None
                                # 일반실 창가 좌석 선택
                                if train.has_general_seat():
                                    general_seats = train.cars[1].select_seats(
                                        count=adult_count + child_count,
                                        position="창측",
                                        seat_type="일반석"
                                    )
                                    if general_seats:
                                        selected_seats = general_seats
                                # 특실 창가 좌석 선택 (일반실 없으면)
                                elif train.has_special_seat():
                                    special_seats = train.cars[1].select_seats(
                                        count=adult_count + child_count,
                                        position="창측",
                                        seat_type="특실"
                                    )
                                    if special_seats:
                                        selected_seats = special_seats

                                if selected_seats:
                                    seat_opt = selected_seats
                                    logger.info(f"창가 좌석 선택 성공: {selected_seats}")
                                elif window_only:
                                    # 창가만 모드인데 창가 좌석 없으면 건너뜀
                                    logger.info("창가 좌석 없음, 다음 열차로 건너뜀")
                                    await asyncio.sleep(self.RATE_LIMIT_DELAY)
                                    continue
                                else:
                                    logger.warning("창가 좌석 선택 실패, 일반 배정으로 진행")

                            except Exception as seat_err:
                                logger.warning(f"창가 좌석 선택 실패: {seat_err}")
                                if window_only:
                                    # 창가만 모드인데 선택 실패하면 건너뜀
                                    await asyncio.sleep(self.RATE_LIMIT_DELAY)
                                    continue

                        reservation = await loop.run_in_executor(None, partial(
                            self.korail.reserve,
                            train,
                            seat_opt=seat_opt
                        ))
                        
                        if reservation:
                            # 예약 성공 처리
                            success_msg = (
                                f"🎉 예약 성공!\n"
                                f"열차: {train_info}\n"
                                f"출발: {dep} ({train.dpt_time[:2]}:{train.dpt_time[2:4]})\n"
                                f"도착: {arr} ({train.arv_time[:2]}:{train.arv_time[2:4]})\n"
                                f"예약번호: {reservation.rsv_no}"
                            )
                            await context.bot.send_message(chat_id=chat_id, text=success_msg)

                            # 예약 정보 반환 (결제 처리를 위해)
                            reservation_info = {
                                'rsv_no': reservation.rsv_no,
                                'train_info': train_info
                            }
                            
                            # KTX 자동 결제 처리
                            korail_payment = KorailAutoPayment()
                            await korail_payment.process_payment(reservation_info, chat_id, context)
                            
                            return reservation_info
                        
                    except Exception as e:
                        error_message = str(e)
                        logger.error(f"KTX 예약 실패 - {train_info} - 사유: {error_message}")
                        
                        # 네트워크 타임아웃 관련 오류 확인
                        if "ConnectTimeout" in repr(e) or "ConnectionError" in repr(e):
                            logger.warning("KTX 서버 연결 타임아웃 발생, 30초 후 재시도합니다.")
                            # 타임아웃 발생 시 더 긴 대기 시간 적용
                            await asyncio.sleep(30)

                            # 세션 재설정
                            try:
                                korail_user = os.environ.get('KORAIL_USER')
                                korail_pass = os.environ.get('KORAIL_PASS')
                                self.korail = Korail()
                                self.korail.login(korail_user.strip(), korail_pass.strip())
                                logger.info("KTX 세션 재설정 완료")
                            except Exception as login_err:
                                logger.error(f"KTX 세션 재설정 실패: {repr(login_err)}")
                        elif ("login" in error_message.lower() or "인증" in error_message or "authentication" in error_message.lower() or
                              "로그아웃" in error_message or "logout" in error_message.lower() or "P058" in error_message):
                            # 로그인 관련 오류인 경우 세션 재설정 후 재시도
                            logger.warning(f"KTX 로그인 오류 발생, 세션 재설정 후 재시도: {error_message}")
                            try:
                                korail_user = os.environ.get('KORAIL_USER')
                                korail_pass = os.environ.get('KORAIL_PASS')
                                self.korail = Korail()
                                self.korail.login(korail_user.strip(), korail_pass.strip())
                                logger.info("KTX 세션 재설정 완료")
                                await asyncio.sleep(5.0)
                            except Exception as login_err:
                                logger.error(f"KTX 세션 재설정 실패: {str(login_err)}")
                                await asyncio.sleep(30.0)
                        else:
                            # 일반적인 오류는 짧은 대기 시간
                            await asyncio.sleep(self.RATE_LIMIT_DELAY)
                        continue
                        
                except Exception as e:
                    logger.error(f"KTX 검색/예약 오류: {repr(e)}")  # str(e) 대신 repr(e) 사용
                    
                    error_str = str(e)
                    # 네트워크 타임아웃 관련 오류 확인
                    if "ConnectTimeout" in repr(e) or "ConnectionError" in repr(e):
                        logger.warning("KTX 서버 연결 타임아웃 발생, 30초 후 재시도합니다.")
                        # 타임아웃 발생 시 더 긴 대기 시간 적용
                        await asyncio.sleep(30)

                        # 세션 재설정
                        try:
                            korail_user = os.environ.get('KORAIL_USER')
                            korail_pass = os.environ.get('KORAIL_PASS')
                            self.korail = Korail()
                            self.korail.login(korail_user.strip(), korail_pass.strip())
                            logger.info("KTX 세션 재설정 완료")
                        except Exception as login_err:
                            logger.error(f"KTX 세션 재설정 실패: {repr(login_err)}")
                    elif ("login" in error_str.lower() or "인증" in error_str or "authentication" in error_str.lower() or
                          "로그아웃" in error_str or "logout" in error_str.lower() or "P058" in error_str):
                        # 로그인 관련 오류인 경우 세션 재설정 후 재시도
                        logger.warning(f"KTX 로그인 오류 발생, 세션 재설정 후 재시도: {error_str}")
                        try:
                            korail_user = os.environ.get('KORAIL_USER')
                            korail_pass = os.environ.get('KORAIL_PASS')
                            self.korail = Korail()
                            self.korail.login(korail_user.strip(), korail_pass.strip())
                            logger.info("KTX 세션 재설정 완료")
                            await asyncio.sleep(5.0)
                        except Exception as login_err:
                            logger.error(f"KTX 세션 재설정 실패: {str(login_err)}")
                            await asyncio.sleep(30.0)
                    else:
                        # 일반적인 오류는 짧은 대기 시간
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
            
            if self.status_manager.stop_event.is_set():
                return "사용자 요청으로 예약이 중단되었습니다."
            
            logger.info(f"KTX 예약 진행 중... (시도 횟수: {total_attempt_count}회)")
            await asyncio.sleep(1.0)

        return "예약 프로세스가 중단되었습니다."

    async def reserve_srt(self, dep, arr, date, time, chat_id, context):
        total_attempt_count = 0
        loop = asyncio.get_event_loop()
        
        # 무한 루프로 변경 (예약 성공할 때까지 계속 시도)
        while not self.status_manager.stop_event.is_set():
            for _ in range(self.ATTEMPTS_PER_CYCLE):
                if self.status_manager.stop_event.is_set():
                    logger.info("SRT 예약 중단 요청 감지")
                    return "사용자 요청으로 예약이 중단되었습니다."

                total_attempt_count += 1

                # 500회마다 로그인 상태 체크 및 재로그인 (약 8-10분마다)
                if total_attempt_count % 500 == 0:
                    logger.info(f"SRT 500회 도달, 정기 재로그인 진행 (시도 #{total_attempt_count})")
                    try:
                        srt_user = os.environ.get('SRT_USER_num')
                        srt_pass = os.environ.get('SRT_PASS')
                        self.srt = SRT(srt_user.strip(), srt_pass.strip())
                        self.srt.login()
                        logger.info("SRT 정기 재로그인 완료")
                        await asyncio.sleep(2.0)
                    except Exception as login_err:
                        logger.error(f"SRT 정기 재로그인 실패: {str(login_err)}")
                        await asyncio.sleep(5.0)

                try:
                    # 열차 검색
                    trains = await loop.run_in_executor(None, partial(
                        self.srt.search_train,
                        dep, arr, date, time,
                        available_only=False  # 모든 열차 검색
                    ))
                    
                    if not trains:
                        # 열차가 없는 경우 처리
                        logger.warning(f"검색된 열차 없음")
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
                        continue

                    # 지정한 시간 이후의 첫번째 열차 선택
                    target_time = int(time)  # 예: 153000
                    train = trains[0]  # 가장 가까운 시간의 첫번째 열차
                    
                    # 여기서 train_info 변수 정의
                    train_info = (f"{date[:4]}/{date[4:6]}/{date[6:]} "
                                 f"{train.dep_time[:2]}:{train.dep_time[2:4]} "
                                 f"SRT {train.train_number}번 열차")

                    # 예약 시도
                    try:
                        adult_count = context.user_data.get('adult_count', 1)
                        child_count = context.user_data.get('child_count', 0)
                        window_seat = context.user_data.get('window_seat', False)
                        
                        passengers = []
                        if adult_count > 0:
                            passengers.append(Adult(adult_count))
                        if child_count > 0:
                            passengers.append(Child(child_count))
                        
                        reservation = await loop.run_in_executor(None, partial(
                            self.srt.reserve,
                            train,
                            passengers=passengers,
                            special_seat=context.user_data.get('seat_type', SeatType.GENERAL_FIRST),
                            window_seat=window_seat
                        ))
                        
                        if reservation:
                            # 예약 성공 처리
                            success_msg = (
                                f"🎉 예약 성공!\n"
                                f"열차: {train_info}\n"
                                f"출발: {dep} ({train.dep_time[:2]}:{train.dep_time[2:4]})\n"
                                f"도착: {arr} ({train.arr_time[:2]}:{train.arr_time[2:4]})\n"
                                f"예약번호: {reservation.reservation_number}"
                            )
                            await context.bot.send_message(chat_id=chat_id, text=success_msg)
                            
                            # 예약 정보 반환 (결제 처리를 위해)
                            reservation_info = {
                                'reservation_number': reservation.reservation_number,
                                'train_info': train_info
                            }
                            
                            # SRT 자동 결제 처리
                            srt_payment = SRTAutoPayment()
                            await srt_payment.process_payment(reservation_info, chat_id, context)
                            
                            return reservation_info
                        
                    except Exception as e:
                        error_message = str(e)
                        logger.error(f"SRT 예약 실패 - {train_info} - 사유: {error_message}")
                        
                        # 네트워크 타임아웃 관련 오류 확인
                        if "ConnectTimeout" in repr(e) or "ConnectionError" in repr(e):
                            logger.warning("SRT 서버 연결 타임아웃 발생, 30초 후 재시도합니다.")
                            # 타임아웃 발생 시 더 긴 대기 시간 적용
                            await asyncio.sleep(30)

                            # 세션 재설정
                            try:
                                srt_user = os.environ.get('SRT_USER_num')
                                srt_pass = os.environ.get('SRT_PASS')
                                self.srt = SRT(srt_user.strip(), srt_pass.strip())
                                self.srt.login()
                                logger.info("SRT 세션 재설정 완료")
                            except Exception as login_err:
                                logger.error(f"SRT 세션 재설정 실패: {repr(login_err)}")
                        elif ("login" in error_message.lower() or "인증" in error_message or "authentication" in error_message.lower() or
                              "로그아웃" in error_message or "logout" in error_message.lower() or "P058" in error_message):
                            # 로그인 관련 오류인 경우 세션 재설정 후 재시도
                            logger.warning(f"SRT 로그인 오류 발생, 세션 재설정 후 재시도: {error_message}")
                            try:
                                srt_user = os.environ.get('SRT_USER_num')
                                srt_pass = os.environ.get('SRT_PASS')
                                self.srt = SRT(srt_user.strip(), srt_pass.strip())
                                self.srt.login()
                                logger.info("SRT 세션 재설정 완료")
                                await asyncio.sleep(5.0)
                            except Exception as login_err:
                                logger.error(f"SRT 세션 재설정 실패: {str(login_err)}")
                                await asyncio.sleep(30.0)
                        else:
                            # 일반적인 오류는 짧은 대기 시간
                            await asyncio.sleep(self.RATE_LIMIT_DELAY)
                        continue
                        
                except Exception as e:
                    logger.error(f"SRT 검색/예약 오류: {repr(e)}")  # str(e) 대신 repr(e) 사용
                    
                    error_str = str(e)
                    # 네트워크 타임아웃 관련 오류 확인
                    if "ConnectTimeout" in repr(e) or "ConnectionError" in repr(e):
                        logger.warning("SRT 서버 연결 타임아웃 발생, 30초 후 재시도합니다.")
                        # 타임아웃 발생 시 더 긴 대기 시간 적용
                        await asyncio.sleep(30)

                        # 세션 재설정
                        try:
                            srt_user = os.environ.get('SRT_USER_num')
                            srt_pass = os.environ.get('SRT_PASS')
                            self.srt = SRT(srt_user.strip(), srt_pass.strip())
                            self.srt.login()
                            logger.info("SRT 세션 재설정 완료")
                        except Exception as login_err:
                            logger.error(f"SRT 세션 재설정 실패: {repr(login_err)}")
                    elif ("login" in error_str.lower() or "인증" in error_str or "authentication" in error_str.lower() or
                          "로그아웃" in error_str or "logout" in error_str.lower() or "P058" in error_str):
                        # 로그인 관련 오류인 경우 세션 재설정 후 재시도
                        logger.warning(f"SRT 로그인 오류 발생, 세션 재설정 후 재시도: {error_str}")
                        try:
                            srt_user = os.environ.get('SRT_USER_num')
                            srt_pass = os.environ.get('SRT_PASS')
                            self.srt = SRT(srt_user.strip(), srt_pass.strip())
                            self.srt.login()
                            logger.info("SRT 세션 재설정 완료")
                            await asyncio.sleep(5.0)
                        except Exception as login_err:
                            logger.error(f"SRT 세션 재설정 실패: {str(login_err)}")
                            await asyncio.sleep(30.0)
                    else:
                        # 일반적인 오류는 짧은 대기 시간
                        await asyncio.sleep(self.RATE_LIMIT_DELAY)
            
            if self.status_manager.stop_event.is_set():
                return "사용자 요청으로 예약이 중단되었습니다."
            
            logger.info(f"SRT 예약 진행 중... (시도 횟수: {total_attempt_count}회)")
            await asyncio.sleep(1.0)

    # 메인 처리 함수 수정
    async def process_srt_task(self, update, context):
        # ... existing code ...
        
        # 상태 초기화 코드 제거 또는 주석 처리
        # 아래 코드가 잔여석이 없을 때도 상태를 초기화하는 원인임
        """
        # 작업 완료 후 상태 초기화
        self.user_states[chat_id] = {
            'state': 'IDLE',
            'data': {}
        }
        logger.info("상태 초기화 완료")
        """

    async def ask_seat_type(self, update, context):
        keyboard = [
            [
                InlineKeyboardButton("특실", callback_data="seat_special"),
                InlineKeyboardButton("일반실", callback_data="seat_general")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Update 객체 또는 CallbackQuery 객체 처리
        if hasattr(update, 'effective_chat'):
            chat_id = update.effective_chat.id
        else:
            chat_id = update.message.chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="좌석 타입을 선택해주세요:",
            reply_markup=reply_markup
        )

    async def search_and_show_trains(self, dep, arr, date, time, service, chat_id, context):
        """열차 검색 및 목록 표시"""
        logger.info(f"열차 검색 시작: {dep} → {arr}, {date}, {time}, {service}")

        try:
            # 서비스에 따라 검색
            if service == 'KTX':
                trains = await self._search_ktx_trains(dep, arr, date, time)
            elif service == 'SRT':
                trains = await self._search_srt_trains(dep, arr, date, time)
            else:
                await context.bot.send_message(chat_id=chat_id, text="❌ 지원하지 않는 서비스입니다.")
                return

            if not trains:
                await context.bot.send_message(chat_id=chat_id, text="❌ 검색된 열차가 없습니다.")
                return

            # 최대 8개 열차 표시
            display_trains = trains[:8]

            # 열차 목록 메시지 생성
            train_list_text = f"🚄 {dep} → {arr} 열차 목록:\n\n"
            for i, train_info in enumerate(display_trains):
                train_list_text += f"[{i+1}] {train_info['display_text'].replace(chr(10), ' | ')}\n\n"

            # 간단한 선택 버튼 생성
            keyboard = []
            row = []
            for i in range(len(display_trains)):
                row.append(InlineKeyboardButton(f"{i+1}번", callback_data=f"select_train_{i}"))
                if len(row) == 4:  # 4열로 배치
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            # 예매 모드 선택 옵션 추가
            keyboard.append([
                InlineKeyboardButton("🎯 다중 모니터링", callback_data="multi_monitor_mode"),
                InlineKeyboardButton("🎫 단일 예매", callback_data="single_booking_mode")
            ])

            # 정렬 옵션 추가
            keyboard.append([
                InlineKeyboardButton("⏱️ 시간순", callback_data="sort_time"),
                InlineKeyboardButton("💰 가격순", callback_data="sort_price"),
                InlineKeyboardButton("🔄 다시검색", callback_data="search_again")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)

            # 검색 결과 저장 (선택 시 사용)
            context.user_data['available_trains'] = display_trains

            await context.bot.send_message(
                chat_id=chat_id,
                text=train_list_text,
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"열차 검색 중 오류: {str(e)}")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ 열차 검색 중 오류가 발생했습니다: {str(e)}")

    async def _search_ktx_trains(self, dep, arr, date, time):
        """KTX 열차 검색"""
        loop = asyncio.get_event_loop()
        trains = await loop.run_in_executor(None, partial(
            self.korail.search_train,
            dep, arr, date, time,
            include_soldout=True  # 매진된 열차도 포함
        ))

        # 지정 시간 이후의 열차만 필터링
        target_time_str = time  # HHMMSS 형식
        target_hour = int(target_time_str[:2])
        target_minute = int(target_time_str[2:4])
        target_second = int(target_time_str[4:])

        from datetime import time as dt_time
        target_time = dt_time(target_hour, target_minute, target_second)

        train_list = []
        for train in trains:
            # 출발 시간 비교
            train_hour = int(train.dpt_time[:2])
            train_minute = int(train.dpt_time[2:4])
            train_second = int(train.dpt_time[4:])
            train_dep_time = dt_time(train_hour, train_minute, train_second)

            # 지정 시간 이후 출발하는 열차만 포함
            if train_dep_time >= target_time:
                # 소요 시간 계산
                dep_dt = datetime.strptime(f"{date} {train.dpt_time}", "%Y%m%d %H%M%S")
                arr_dt = datetime.strptime(f"{date} {train.arv_time}", "%Y%m%d %H%M%S")
                if arr_dt < dep_dt:  # 다음날 도착
                    arr_dt += timedelta(days=1)
                duration = arr_dt - dep_dt
                duration_str = f"{duration.seconds // 3600}시간 {duration.seconds % 3600 // 60}분"

                # 가격 정보 (임시 - 실제로는 API에서 가져와야 함)
                price = "52,000원" if train.train_type == "100" else "45,000원"

                train_info = {
                    'train': train,
                    'display_text': f"🚄 KTX {train.train_no}\n⏰ {train.dpt_time[:2]}:{train.dpt_time[2:4]} → {train.arv_time[:2]}:{train.arv_time[2:4]}\n⏱️ {duration_str}",
                    'duration': duration,
                    'price': price
                }
                train_list.append(train_info)

        # 출발 시간순 정렬
        return sorted(train_list, key=lambda x: x['train'].dpt_time)

    def reserve_selected_train(self, selected_train, user_data, chat_id, context):
        """선택된 열차로 예약 진행"""
        logger.info(f"선택된 열차로 예약 시작: {selected_train}")

        # 로그인 상태 확인
        if not self.check_login_status():
            logger.error("로그인 상태가 올바르지 않습니다. 예약을 시작할 수 없습니다.")
            asyncio.create_task(context.bot.send_message(
                chat_id=chat_id,
                text="❌ 로그인 상태 오류로 예약을 시작할 수 없습니다."
            ))
            return

        # StatusManager 상태 설정
        self.status_manager.start_reservation(chat_id)
        logger.info(f"예약 상태 관리 시작 - chat_id: {chat_id}")

        # 예약 옵션 설정
        seat_type = user_data.get('seat_type', SeatType.GENERAL_FIRST)
        window_seat = user_data.get('window_seat', False)

        logger.info(f"예약 옵션 - 좌석타입: {seat_type}, 창가좌석: {window_seat}")
        logger.info(f"사용자 데이터: {user_data}")

        # 예약 시도 (예외 처리 추가)
        try:
            task = asyncio.create_task(self._reserve_selected_train_async(
                selected_train, seat_type, window_seat, user_data, chat_id, context
            ))
            self.reservation_task = task
            logger.info("비동기 예약 태스크 생성 및 시작")

            # 태스크 예외 처리를 위한 콜백 추가
            def task_done_callback(task):
                try:
                    result = task.result()
                    logger.info(f"예약 태스크 완료: {result}")
                except asyncio.CancelledError:
                    logger.info("예약 태스크가 사용자에 의해 취소되었습니다")
                    # CancelledError는 정상적인 취소이므로 별도 알림 없음
                except Exception as e:
                    logger.error(f"예약 태스크에서 예외 발생: {str(e)}")
                    # 비동기 태스크 내에서 안전하게 메시지 전송
                    try:
                        loop = asyncio.get_event_loop()
                        if not loop.is_closed():
                            asyncio.create_task(context.bot.send_message(
                                chat_id=chat_id,
                                text=f"❌ 예약 중 예외 발생: {str(e)}"
                            ))
                    except Exception as send_err:
                        logger.error(f"오류 메시지 전송 실패: {str(send_err)}")

            task.add_done_callback(task_done_callback)

        except Exception as e:
            logger.error(f"예약 태스크 생성 중 오류: {str(e)}")
            asyncio.create_task(context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 예약 시작 중 오류 발생: {str(e)}"
            ))

    async def _reserve_selected_train_async(self, selected_train, seat_type, window_seat, user_data, chat_id, context):
        """선택된 열차 비동기 예약"""
        attempt_count = 0
        logger.info("비동기 예약 프로세스 시작")

        while not self.status_manager.stop_event.is_set():  # /stop 명령어로만 중단
            try:
                attempt_count += 1
                logger.info(f"예약 시도 #{attempt_count}")

                # 500회마다 로그인 상태 체크 및 재로그인 (약 8-10분마다)
                if attempt_count % 500 == 0:
                    logger.info(f"500회 도달, 로그인 상태 체크 및 재로그인 진행 (시도 #{attempt_count})")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔄 정기 로그인 갱신 중... (시도 #{attempt_count}회)"
                    )
                    try:
                        if hasattr(selected_train, 'train_no'):  # KTX
                            korail_user = os.environ.get('KORAIL_USER')
                            korail_pass = os.environ.get('KORAIL_PASS')
                            self.korail = Korail()
                            self.korail.login(korail_user.strip(), korail_pass.strip())
                            logger.info("KTX 정기 재로그인 완료")
                        else:  # SRT
                            srt_user = os.environ.get('SRT_USER_num')
                            srt_pass = os.environ.get('SRT_PASS')
                            self.srt = SRT(srt_user.strip(), srt_pass.strip())
                            self.srt.login()
                            logger.info("SRT 정기 재로그인 완료")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="✅ 로그인 갱신 완료, 예약 시도 계속합니다"
                        )
                        await asyncio.sleep(2.0)  # 재로그인 후 잠시 대기
                    except Exception as login_err:
                        logger.error(f"정기 재로그인 실패: {str(login_err)}")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="⚠️ 로그인 갱신 실패, 계속 시도합니다"
                        )
                        await asyncio.sleep(5.0)

                loop = asyncio.get_event_loop()

                # KTX 예약
                if hasattr(selected_train, 'train_no'):  # KTX
                    logger.info(f"KTX 예약 시도 - 열차번호: {selected_train.train_no}")
                    reservation = await loop.run_in_executor(None, partial(
                        self.korail.reserve,
                        selected_train,
                        seat_opt=seat_type
                    ))

                    if reservation:
                        # reservation 객체가 생성되면 예약 성공으로 간주
                        try:
                            # 예약번호 안전하게 가져오기 (여러 속성명 시도)
                            rsv_no = None
                            for attr_name in ['rsv_no', 'rsv_id', 'reservation_number']:
                                rsv_no = getattr(reservation, attr_name, None)
                                if rsv_no:
                                    logger.info(f"예약번호 발견: {attr_name} = {rsv_no}")
                                    break

                            if not rsv_no:
                                rsv_no = "UNKNOWN"
                                logger.warning("예약번호를 찾을 수 없음, 기본값 사용")

                            success_msg = (
                                f"🎉 KTX 예약 성공!\n"
                                f"열차: {selected_train.train_no}번\n"
                                f"출발: {user_data['departure']} ({selected_train.dpt_time[:2]}:{selected_train.dpt_time[2:4]})\n"
                                f"도착: {user_data['destination']} ({selected_train.arv_time[:2]}:{selected_train.arv_time[2:4]})\n"
                                f"예약번호: {rsv_no}"
                            )
                            await context.bot.send_message(chat_id=chat_id, text=success_msg)

                            # 결제 진행
                            reservation_info = {
                                'rsv_no': rsv_no,
                                'train_info': f"{user_data['date'][:4]}/{user_data['date'][4:6]}/{user_data['date'][6:]} KTX {selected_train.train_no}번"
                            }
                            korail_payment = KorailAutoPayment()
                            await korail_payment.process_payment(reservation_info, chat_id, context)
                            return

                        except Exception as attr_err:
                            # 속성 오류가 발생해도 예약은 성공한 것으로 간주
                            logger.warning(f"예약 성공했지만 속성 오류 발생: {str(attr_err)}")
                            success_msg = (
                                f"🎉 KTX 예약 성공!\n"
                                f"열차: {selected_train.train_no}번\n"
                                f"출발: {user_data['departure']} ({selected_train.dpt_time[:2]}:{selected_train.dpt_time[2:4]})\n"
                                f"도착: {user_data['destination']} ({selected_train.arv_time[:2]}:{selected_train.arv_time[2:4]})\n"
                                f"예약번호: 속성 오류로 확인 불가"
                            )
                            await context.bot.send_message(chat_id=chat_id, text=success_msg)

                            # 가짜 예약 정보로 결제 프로세스 진행
                            reservation_info = {
                                'rsv_no': "ATTR_ERROR_RESERVATION",
                                'train_info': f"{user_data['date'][:4]}/{user_data['date'][4:6]}/{user_data['date'][6:]} KTX {selected_train.train_no}번"
                            }
                            korail_payment = KorailAutoPayment()
                            await korail_payment.process_payment(reservation_info, chat_id, context)
                            return

                # SRT 예약
                elif hasattr(selected_train, 'train_number'):  # SRT
                    adult_count = user_data.get('adult_count', 1)
                    child_count = user_data.get('child_count', 0)

                    passengers = []
                    if adult_count > 0:
                        passengers.append(Adult(adult_count))
                    if child_count > 0:
                        passengers.append(Child(child_count))

                    reservation = await loop.run_in_executor(None, partial(
                        self.srt.reserve,
                        selected_train,
                        passengers=passengers,
                        special_seat=(seat_type == SeatType.SPECIAL_ONLY),
                        window_seat=window_seat
                    ))

                    if reservation:
                        success_msg = (
                            f"🎉 SRT 예약 성공!\n"
                            f"열차: {selected_train.train_number}번\n"
                            f"출발: {user_data['departure']} ({selected_train.dep_time.strftime('%H:%M')})\n"
                            f"도착: {user_data['destination']} ({selected_train.arr_time.strftime('%H:%M')})\n"
                            f"예약번호: {reservation.reservation_number}"
                        )
                        await context.bot.send_message(chat_id=chat_id, text=success_msg)

                        # 결제 진행
                        reservation_info = {
                            'reservation_number': reservation.reservation_number,
                            'train_info': f"{user_data['date'][:4]}/{user_data['date'][4:6]}/{user_data['date'][6:]} SRT {selected_train.train_number}번"
                        }
                        srt_payment = SRTAutoPayment()
                        await srt_payment.process_payment(reservation_info, chat_id, context)
                        return

                # 예약 성공시 리턴하므로 여기까지 오면 실패
                # 주기적으로 사용자에게 진행 상황 알림
                if attempt_count % 30 == 0:  # 30회마다 (약 30초마다)
                    progress_msg = f"🔄 예약 시도 중... (시도 #{attempt_count}회)\n계속 시도하고 있습니다. 중단하려면 /stop 명령어를 사용하세요."
                    await context.bot.send_message(chat_id=chat_id, text=progress_msg)

                # 1분에 60회 이내로 제한 (약 1초에 1회)
                await asyncio.sleep(1.0)

            except Exception as e:
                error_str = str(e)
                logger.warning(f"예약 시도 #{attempt_count} 실패: {error_str}")

                # 중복 예약 오류 - 이미 예약이 성공한 상태
                if "동일한 예약 내역이 있으니" in error_str or "WRR800029" in error_str:
                    logger.info("중복 예약 오류 감지 - 이미 예약이 성공한 상태입니다")
                    success_msg = (
                        f"🎉 예약 성공! (중복 예약 오류로 확인됨)\n"
                        f"열차: {selected_train.train_no}번\n"
                        f"출발: {user_data['departure']} ({selected_train.dpt_time[:2]}:{selected_train.dpt_time[2:4]})\n"
                        f"도착: {user_data['destination']} ({selected_train.arv_time[:2]}:{selected_train.arv_time[2:4]})\n"
                        f"기존 예약이 있어 중복 예약이 불가능한 상태입니다."
                    )
                    await context.bot.send_message(chat_id=chat_id, text=success_msg)

                    # 가짜 예약 정보로 결제 프로세스 진행
                    reservation_info = {
                        'rsv_no': "DUPLICATE_RESERVATION",
                        'train_info': f"{user_data['date'][:4]}/{user_data['date'][4:6]}/{user_data['date'][6:]} KTX {selected_train.train_no}번"
                    }
                    korail_payment = KorailAutoPayment()
                    await korail_payment.process_payment(reservation_info, chat_id, context)
                    return

                elif "매진" in error_str or "sold out" in error_str.lower() or "좌석" in error_str:
                    # 매진인 경우 계속 시도 (조용히)
                    logger.debug(f"매진으로 인한 실패, 재시도 중...")
                    await asyncio.sleep(1.0)
                    continue
                elif "ConnectTimeout" in repr(e) or "ConnectionError" in repr(e) or "TimeoutError" in repr(e):
                    # 네트워크 오류인 경우 잠시 대기 후 계속 시도
                    logger.warning(f"네트워크 오류 발생, 10초 후 재시도: {error_str}")
                    await asyncio.sleep(10.0)
                    continue
                elif ("login" in error_str.lower() or "인증" in error_str or "authentication" in error_str.lower() or
                      "로그아웃" in error_str or "logout" in error_str.lower() or "P058" in error_str):
                    # 로그인 관련 오류인 경우 세션 재설정 후 재시도
                    logger.warning(f"로그인 오류 발생, 세션 재설정 후 재시도: {error_str}")
                    try:
                        # 세션 재설정
                        if hasattr(selected_train, 'train_no'):  # KTX
                            korail_user = os.environ.get('KORAIL_USER')
                            korail_pass = os.environ.get('KORAIL_PASS')
                            self.korail = Korail()
                            self.korail.login(korail_user.strip(), korail_pass.strip())
                            logger.info("KTX 세션 재설정 완료")
                        else:  # SRT
                            srt_user = os.environ.get('SRT_USER_num')
                            srt_pass = os.environ.get('SRT_PASS')
                            self.srt = SRT(srt_user.strip(), srt_pass.strip())
                            self.srt.login()
                            logger.info("SRT 세션 재설정 완료")
                        await asyncio.sleep(5.0)
                        continue
                    except Exception as login_err:
                        logger.error(f"세션 재설정 실패: {str(login_err)}")
                        await asyncio.sleep(30.0)
                        continue
                else:
                    # 기타 오류도 재시도 (단, 경고 메시지 출력)
                    logger.warning(f"예상치 못한 오류 발생, 재시도 중: {error_str}")
                    if attempt_count % 10 == 0:  # 10회마다 사용자에게 알림
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"⚠️ 예약 시도 중 오류가 발생했지만 계속 시도하고 있습니다 (시도 #{attempt_count})"
                        )
                    await asyncio.sleep(5.0)
                    continue

        # 이 지점에 도달하면 /stop에 의해 중단된 것임
        logger.info("예약 프로세스가 사용자에 의해 중단되었습니다.")

    async def _search_srt_trains(self, dep, arr, date, time):
        """SRT 열차 검색"""
        loop = asyncio.get_event_loop()
        trains = await loop.run_in_executor(None, partial(
            self.srt.search_train,
            dep, arr, date, time,
            available_only=True  # 잔여석 있는 것만
        ))

        # 지정 시간 이후의 열차만 필터링
        target_time_str = time  # HHMMSS 형식
        target_hour = int(target_time_str[:2])
        target_minute = int(target_time_str[2:4])
        target_second = int(target_time_str[4:])

        from datetime import time as dt_time
        target_time = dt_time(target_hour, target_minute, target_second)

        train_list = []
        for train in trains:
            # 출발 시간 비교
            train_dep_time = train.dep_time.time()

            # 지정 시간 이후 출발하는 열차만 포함
            if train_dep_time >= target_time:
                # 소요 시간 계산
                duration = train.arr_time - train.dep_time
                duration_str = f"{duration.seconds // 3600}시간 {duration.seconds % 3600 // 60}분"

                # 가격 정보 (임시)
                price = "57,000원"  # SRT 기본 가격

                train_info = {
                    'train': train,
                    'display_text': f"🚄 SRT {train.train_number}\n⏰ {train.dep_time.strftime('%H:%M')} → {train.arr_time.strftime('%H:%M')}\n⏱️ {duration_str}",
                    'duration': duration,
                    'price': price
                }
                train_list.append(train_info)

        # 출발 시간순 정렬
        return sorted(train_list, key=lambda x: x['train'].dep_time)

    async def handle_seat_selection(self, update, context):
        query = update.callback_query
        choice = query.data
        
        if choice == "seat_special":
            context.user_data['seat_type'] = SeatType.SPECIAL_ONLY
            await query.edit_message_text("특실로 예약을 시도합니다.")
        else:
            context.user_data['seat_type'] = SeatType.GENERAL_ONLY
            await query.edit_message_text("일반실로 예약을 시도합니다.")
        
        # 예약 프로세스 시작
        await self.start_reservation(update, context)

    # 인원수 선택 대화 상자
    async def ask_passenger_count(self, update, context):
        keyboard = [
            [InlineKeyboardButton("어른 1명", callback_data="adult_1"),
             InlineKeyboardButton("어른 2명", callback_data="adult_2")],
            [InlineKeyboardButton("어른 3명", callback_data="adult_3"),
             InlineKeyboardButton("어른 4명", callback_data="adult_4")],
            [InlineKeyboardButton("직접 입력", callback_data="adult_manual")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Update 객체 또는 CallbackQuery 객체 처리
        if hasattr(update, 'effective_chat'):
            chat_id = update.effective_chat.id
        else:
            chat_id = update.message.chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="어른 인원수를 선택해주세요:",
            reply_markup=reply_markup
        )

    # 어린이 수 입력
    async def ask_child_count(self, update, context):
        keyboard = [
            [InlineKeyboardButton("어린이 0명", callback_data="child_0"),
             InlineKeyboardButton("어린이 1명", callback_data="child_1")],
            [InlineKeyboardButton("어린이 2명", callback_data="child_2"),
             InlineKeyboardButton("어린이 3명", callback_data="child_3")],
            [InlineKeyboardButton("어린이 4명", callback_data="child_4"),
             InlineKeyboardButton("직접 입력", callback_data="child_manual")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Update 객체 또는 CallbackQuery 객체 처리
        if hasattr(update, 'effective_chat'):
            chat_id = update.effective_chat.id
        else:
            chat_id = update.message.chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="어린이 인원수를 선택해주세요:",
            reply_markup=reply_markup
        )

    # 창가자리 여부 선택
    async def ask_window_seat(self, update, context):
        # child_count는 이미 context.user_data에 저장되어 있음

        keyboard = [
            [
                InlineKeyboardButton("창가 우선", callback_data="window_priority"),
                InlineKeyboardButton("창가만", callback_data="window_only"),
                InlineKeyboardButton("상관없음", callback_data="window_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        chat_id = update.effective_chat.id if hasattr(update, 'effective_chat') else update.callback_query.message.chat.id

        await context.bot.send_message(
            chat_id=chat_id,
            text="창가자리 배정 방식을 선택해주세요:",
            reply_markup=reply_markup
        )

def create_calendar(year=None, month=None):
    """
    지정된 년월에 대한 달력 인라인 키보드를 생성합니다.
    """
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month

    # 달력 데이터 생성
    cal = calendar.monthcalendar(year, month)

    # 키보드 생성
    keyboard = []

    # 월/년 헤더
    header = f"{year}년 {month}월"
    keyboard.append([InlineKeyboardButton(header, callback_data="ignore")])

    # 요일 헤더
    weekday_header = [InlineKeyboardButton(day, callback_data="ignore") for day in DAYS_OF_WEEK]
    keyboard.append(weekday_header)

    # 날짜 버튼들
    for week in cal:
        week_buttons = []
        for day in week:
            if day == 0:
                # 빈 칸
                week_buttons.append(InlineKeyboardButton(" ", callback_data="ignore"))
            else:
                date_str = f"{day:02d}"
                callback_data = f"date_{year}{month:02d}{day:02d}"
                week_buttons.append(InlineKeyboardButton(str(day), callback_data=callback_data))
        keyboard.append(week_buttons)

    # 내비게이션 버튼 (이전/다음 달, 오늘/내일/모레)
    nav_row = [
        InlineKeyboardButton("◀ 이전", callback_data=f"cal_{year}_{month-1 if month > 1 else 12}_{year if month > 1 else year-1}"),
        InlineKeyboardButton("오늘", callback_data="date_today"),
        InlineKeyboardButton("내일", callback_data="date_tomorrow"),
        InlineKeyboardButton("모레", callback_data="date_day_after"),
        InlineKeyboardButton("다음 ▶", callback_data=f"cal_{year}_{month+1 if month < 12 else 1}_{year if month < 12 else year+1}")
    ]
    keyboard.append(nav_row)

    return InlineKeyboardMarkup(keyboard)

def create_time_selector(selected_hour=None, selected_minute=None):
    """
    시간 선택을 위한 인터페이스를 생성합니다.
    선택된 시간/분을 강조 표시합니다.
    """
    keyboard = []

    # 현재 선택 상태 표시
    current_time = f"선택된 시간: {selected_hour or '??'}:{selected_minute or '??'}"
    keyboard.append([InlineKeyboardButton(current_time, callback_data="ignore")])

    # 시간 선택 (1시간 단위, 4열로 배치)
    keyboard.append([InlineKeyboardButton("🕐 시간 선택", callback_data="ignore")])
    hour_row = []
    for hour in range(6, 22):  # 06:00 ~ 21:00
        hour_text = f"{hour:02d}"
        if selected_hour == hour:
            hour_text = f"✅ {hour_text}"
        hour_row.append(InlineKeyboardButton(hour_text, callback_data=f"time_hour_{hour:02d}"))
        if len(hour_row) == 4:
            keyboard.append(hour_row)
            hour_row = []
    if hour_row:
        keyboard.append(hour_row)

    # 분 선택 (5분 단위, 6열로 배치)
    keyboard.append([InlineKeyboardButton("🕑 분 선택", callback_data="ignore")])
    minute_row = []
    for minute in range(0, 60, 5):
        minute_text = f"{minute:02d}"
        if selected_minute == minute:
            minute_text = f"✅ {minute_text}"
        minute_row.append(InlineKeyboardButton(minute_text, callback_data=f"time_minute_{minute:02d}"))
        if len(minute_row) == 6:
            keyboard.append(minute_row)
            minute_row = []
    if minute_row:
        keyboard.append(minute_row)

    # 확인/취소 버튼
    keyboard.append([
        InlineKeyboardButton("✅ 확인", callback_data="time_confirm"),
        InlineKeyboardButton("🔄 초기화", callback_data="time_reset"),
        InlineKeyboardButton("❌ 취소", callback_data="time_cancel")
    ])

    return InlineKeyboardMarkup(keyboard)

def create_quick_routes():
    """
    빠른 경로 선택 키보드를 생성합니다.
    """
    keyboard = [
        [InlineKeyboardButton("🚄 KTX: 서울 → 부산", callback_data="route_ktx_seoul_busan")],
        [InlineKeyboardButton("🚄 KTX: 부산 → 서울", callback_data="route_ktx_busan_seoul")],
        [InlineKeyboardButton("🚄 SRT: 서울(수서) → 부산", callback_data="route_seoul_busan")],
        [InlineKeyboardButton("🚄 SRT: 부산 → 서울(수서)", callback_data="route_busan_seoul")],
        [InlineKeyboardButton("직접 입력", callback_data="route_custom")]
    ]
    return InlineKeyboardMarkup(keyboard)

# TrainReservation 객체 생성 (로그인 포함)
try:
    logger.info("TrainReservation 객체 생성 중...")
    train_reservation = TrainReservation()
    logger.info("TrainReservation 객체 생성 완료")
except Exception as e:
    logger.error(f"TrainReservation 초기화 실패: {str(e)}")
    print(f"ERROR: TrainReservation 초기화 실패: {str(e)}")
    print("환경변수 설정을 확인하세요 (.env 파일)")
    sys.exit(1)

# 파이프라인 시스템 초기화
logger.info("파이프라인 시스템 초기화 중...")
target_registry = TargetRegistry()
reservation_executor = ReservationExecutor(train_reservation, target_registry)
scanner_worker = ScannerWorker(target_registry, reservation_executor, train_reservation)

# TrainReservation과 파이프라인 연결
train_reservation.attach_pipeline(target_registry, scanner_worker, reservation_executor)
logger.info("파이프라인 시스템 초기화 완료")

async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # 빠른 경로 옵션 제공
    quick_routes_markup = create_quick_routes()
    await update.message.reply_text(
        '🚄 기차 예약 봇\n\n'
        '빠른 경로를 선택하거나 상세 예약을 진행하세요:\n\n'
        '📋 빠른 경로:\n'
        '• KTX: 서울 ↔ 부산\n'
        '• SRT: 수서 ↔ 부산\n\n'
        '🔧 상세 예약: /manual\n'
        '📊 상태 확인: /status\n'
        '⏹️ 예약 중단: /stop\n\n'
        '빠른 경로를 선택하세요:',
        reply_markup=quick_routes_markup
    )
    return TRAIN_SERVICE

async def set_ktx(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['service'] = 'KTX'
    await update.message.reply_text('출발지를 입력해주세요:')
    return DEPARTURE

async def set_srt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['service'] = 'SRT'
    await update.message.reply_text('출발지를 입력해주세요:')
    return DEPARTURE

async def departure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['departure'] = update.message.text
    await update.message.reply_text('도착지를 입력해주세요:')
    return DESTINATION

async def destination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['destination'] = update.message.text
    await update.message.reply_text('여행 날짜를 입력해주세요 (예: 20240324):')
    return DATE

async def date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # 달력 표시
    calendar_markup = create_calendar()
    await update.message.reply_text('여행 날짜를 선택해주세요:', reply_markup=calendar_markup)
    return TIME  # 날짜 선택 후 바로 시간 선택으로 이동

async def time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        input_time = update.message.text
        datetime.strptime(input_time, '%H%M%S')
        context.user_data['time'] = input_time
        
        # 이 부분을 수정: 예약 프로세스를 바로 시작하지 않고 추가 정보를 물어봄
        await train_reservation.ask_passenger_count(update, context)
        return ConversationHandler.END  # 대화 상태는 종료하고 메시지 핸들러로 처리
        
    except ValueError:
        await update.message.reply_text('올바른 시간 형식이 아닙니다. HHMMSS 형식으로 다시 입력해주세요 (예: 130000):')
        return TIME

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """예약 중단 명령어 처리"""
    chat_id = update.effective_chat.id
    logger.info(f"Stop 명령어 수신 from user {chat_id}")

    train_reservation.stop_reservation_task()

    if train_reservation.status_manager.stop_reservation(chat_id):
        await update.message.reply_text('예약을 중단합니다. 잠시만 기다려주세요...')
    else:
        await update.message.reply_text('현재 실행 중인 예약이 없습니다.')

    return ConversationHandler.END

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """예약 상태 확인 명령어 처리"""
    chat_id = update.effective_chat.id

    status_info = train_reservation.status_manager._load_status()
    if status_info and status_info.get('is_running') and str(status_info.get('chat_id')) == str(chat_id):
        await update.message.reply_text('🔄 현재 예약이 진행 중입니다. 중단하려면 /stop 명령어를 사용하세요.')
    else:
        await update.message.reply_text('⏹️ 현재 실행 중인 예약이 없습니다.')

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('예약 프로세스가 취소되었습니다.')
    return ConversationHandler.END

# 다중 코스 관련 명령어들
async def add_multi_course(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """다중 코스 추가 명령어 - 사용법 안내"""
    help_text = """
🎯 다중 코스 예매 시스템

여러 열차 시간을 동시에 모니터링하여 표가 나오면 우선순위에 따라 자동 예매합니다.

📋 사용법:
/add_multi_course
서울,부산,20250105,080000,SRT,1
서울,부산,20250105,100000,KTX,2
서울,부산,20250105,120000,SRT,3

각 줄 형식: 출발지,도착지,날짜(YYYYMMDD),시간(HHMMSS),서비스(KTX/SRT),우선순위

💡 팁:
- 우선순위는 1이 가장 높음
- 먼저 표가 발견된 시간대로 예매 진행
- /multi_status로 현재 상태 확인 가능
- /stop_multi로 다중 코스 모니터링 중단
"""
    await update.message.reply_text(help_text)

async def multi_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """다중 코스 상태 확인"""
    chat_id = update.effective_chat.id
    targets = await target_registry.list_targets(chat_id)

    if not targets:
        await update.message.reply_text('📭 현재 등록된 코스가 없습니다.')
        return

    # 그룹별로 정리
    groups = {}
    individual = []

    for target in targets:
        if target.group_id:
            if target.group_id not in groups:
                groups[target.group_id] = []
            groups[target.group_id].append(target)
        else:
            individual.append(target)

    status_text = "📊 현재 모니터링 상태\n\n"

    # 다중 코스 그룹들
    for group_id, group_targets in groups.items():
        status_text += f"🎯 그룹 {group_id[:6]}...\n"
        for target in sorted(group_targets, key=lambda t: t.priority):
            mode = "🔍 확인중" if target.scan_only else "🎫 예매중"
            status = "🟢 활성" if target.is_active else "🔴 비활성"
            next_scan = target.next_scan.strftime('%H:%M:%S') if target.next_scan else "대기"
            status_text += f"  {target.priority}. {target.departure}→{target.arrival} {target.time[:2]}:{target.time[2:4]} ({target.service}) {mode} {status} 다음:{next_scan}\n"
        status_text += "\n"

    # 개별 코스들
    if individual:
        status_text += "🎯 개별 코스\n"
        for target in individual:
            mode = "🔍 확인중" if target.scan_only else "🎫 예매중"
            status = "🟢 활성" if target.is_active else "🔴 비활성"
            next_scan = target.next_scan.strftime('%H:%M:%S') if target.next_scan else "대기"
            status_text += f"  {target.departure}→{target.arrival} {target.time[:2]}:{target.time[2:4]} ({target.service}) {mode} {status} 다음:{next_scan}\n"

    await update.message.reply_text(status_text)

async def stop_multi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """모든 다중 코스 모니터링 중단"""
    chat_id = update.effective_chat.id
    count = await target_registry.clear_targets(chat_id)

    if count > 0:
        await update.message.reply_text(f'🛑 {count}개의 코스 모니터링을 중단했습니다.')
    else:
        await update.message.reply_text('📭 중단할 코스가 없습니다.')

async def handle_multi_course_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """다중 코스 입력 처리"""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if not text or text.startswith('/'):
        return

    # 이전 메시지가 다중 코스 명령어였는지 확인
    try:
        lines = text.split('\n')
        courses = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = [p.strip() for p in line.split(',')]
            if len(parts) != 6:
                await update.message.reply_text(f'❌ 잘못된 형식: {line}\n올바른 형식: 출발지,도착지,날짜,시간,서비스,우선순위')
                return

            departure, arrival, date, time, service, priority = parts

            # 유효성 검사
            if len(date) != 8 or not date.isdigit():
                await update.message.reply_text(f'❌ 잘못된 날짜 형식: {date} (YYYYMMDD 형식 필요)')
                return

            if len(time) != 6 or not time.isdigit():
                await update.message.reply_text(f'❌ 잘못된 시간 형식: {time} (HHMMSS 형식 필요)')
                return

            if service.upper() not in ['KTX', 'SRT']:
                await update.message.reply_text(f'❌ 지원하지 않는 서비스: {service} (KTX 또는 SRT만 가능)')
                return

            try:
                priority_num = int(priority)
            except ValueError:
                await update.message.reply_text(f'❌ 잘못된 우선순위: {priority} (숫자여야 함)')
                return

            courses.append({
                'service': service.upper(),
                'departure': departure,
                'arrival': arrival,
                'date': date,
                'time': time,
                'priority': priority_num
            })

        if not courses:
            await update.message.reply_text('❌ 추가할 코스가 없습니다.')
            return

        # 다중 코스 그룹 추가
        targets = await target_registry.add_target_group(
            chat_id=chat_id,
            targets_data=courses
        )

        group_id = targets[0].group_id
        await update.message.reply_text(
            f'✅ {len(courses)}개 코스가 그룹 {group_id[:6]}...으로 등록되었습니다.\n'
            f'모니터링을 시작합니다. /multi_status로 상태를 확인하세요.'
        )

    except Exception as e:
        logger.error(f"다중 코스 처리 오류: {e}")
        await update.message.reply_text(f'❌ 처리 중 오류가 발생했습니다: {str(e)}')

# 빠른 경로 예약 명령어들
async def quick_seoul_busan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """서울 → 부산 빠른 예약"""
    context.user_data['service'] = 'SRT'  # SRT가 더 빠름
    context.user_data['departure'] = '수서'  # SRT는 수서역에서 출발
    context.user_data['destination'] = '부산'

    # 달력 표시
    calendar_markup = create_calendar()
    await update.message.reply_text('🚄 서울(수서) → 부산\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)
    return TIME

async def quick_busan_seoul(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """부산 → 서울 빠른 예약"""
    context.user_data['service'] = 'SRT'
    context.user_data['departure'] = '부산'
    context.user_data['destination'] = '수서'  # SRT는 수서역으로 도착

    # 달력 표시
    calendar_markup = create_calendar()
    await update.message.reply_text('🚄 부산 → 서울(수서)\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)
    return TIME

async def manual_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """기존 텍스트 입력 방식으로 예약"""
    await update.message.reply_text('기존 방식으로 예약을 진행합니다.\n예약할 열차 서비스를 선택하세요 (/ktx 또는 /srt):')
    return TRAIN_SERVICE

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """에러 핸들러"""
    logger.error(f"Exception while handling an update: {context.error}")

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("처리 중 오류가 발생했습니다. 다시 시도해주세요.")
        except Exception:
            pass

def main():
    # 이벤트 루프 설정
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 보안 설정에서 Telegram Bot Token 가져오기
    telegram_bot_token = get_credential('TELEGRAM_BOT_TOKEN')

    # 토큰 유효성 검사
    if not telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
        sys.exit(1)

    application = Application.builder().token(telegram_bot_token).build()

    # 에러 핸들러 등록
    application.add_error_handler(error_handler)

    # stop 명령어 핸들러를 최우선 등록
    application.add_handler(CommandHandler('stop', stop), group=-1)
    application.add_handler(CommandHandler('status', status), group=-1)

    # 빠른 경로 명령어 핸들러 등록
    application.add_handler(CommandHandler('seoul_busan', quick_seoul_busan))
    application.add_handler(CommandHandler('busan_seoul', quick_busan_seoul))
    application.add_handler(CommandHandler('manual', manual_booking))

    # 다중 코스 명령어 핸들러 등록
    application.add_handler(CommandHandler('add_multi_course', add_multi_course))
    application.add_handler(CommandHandler('multi_status', multi_status))
    application.add_handler(CommandHandler('stop_multi', stop_multi))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_search)],
        states={
            TRAIN_SERVICE: [CommandHandler('ktx', set_ktx), CommandHandler('srt', set_srt)],
            DEPARTURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, departure)],
            DESTINATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, destination)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, date)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time)]
        },
        fallbacks=[CommandHandler('stop', stop), CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    
    # 사용자 입력 처리를 위한 메시지 핸들러 추가
    async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """텍스트 입력 처리 핸들러"""
        text = update.message.text.strip()

        # 다중 코스 형식 감지 (쉼표가 있고 여러 줄인 경우)
        if ',' in text and ('\n' in text or len(text.split(',')) >= 6):
            await handle_multi_course_input(update, context)
            return

        if 'expect_input' not in context.user_data:
            return

        expect_input = context.user_data['expect_input']
        if expect_input == 'adult_count':
            # 성인 수 입력 처리
            try:
                adult_count = int(update.message.text)
                context.user_data['adult_count'] = adult_count
                await update.message.reply_text(f"어른 {adult_count}명 입력됨")
                # expect_input 제거
                del context.user_data['expect_input']
                await train_reservation.ask_child_count(update, context)
            except ValueError:
                await update.message.reply_text("올바른 숫자를 입력해주세요:")
        elif expect_input == 'child_count':
            # 어린이 수 입력 처리
            try:
                child_count = int(update.message.text)
                context.user_data['child_count'] = child_count
                await update.message.reply_text(f"어린이 {child_count}명 입력됨")
                # expect_input 제거
                del context.user_data['expect_input']
                await train_reservation.ask_window_seat(update, context)
            except ValueError:
                await update.message.reply_text("올바른 숫자를 입력해주세요:")
            
    # 콜백 쿼리 핸들러 추가
    async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """콜백 쿼리 처리 핸들러"""
        query = update.callback_query
        choice = query.data

        # 달력 관련 콜백
        if choice.startswith("cal_"):
            # 달력 내비게이션: cal_year_month_year
            parts = choice.split("_")
            year = int(parts[1])
            month = int(parts[2])
            new_calendar = create_calendar(year, month)
            await query.edit_message_reply_markup(reply_markup=new_calendar)

        elif choice.startswith("date_"):
            if choice == "date_today":
                selected_date = datetime.now().strftime("%Y%m%d")
                date_text = "오늘"
            elif choice == "date_tomorrow":
                selected_date = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
                date_text = "내일"
            elif choice == "date_day_after":
                selected_date = (datetime.now() + timedelta(days=2)).strftime("%Y%m%d")
                date_text = "모레"
            else:
                # date_YYYYMMDD 형식
                selected_date = choice[5:]  # date_ 제거
                date_obj = datetime.strptime(selected_date, "%Y%m%d")
                date_text = date_obj.strftime("%Y년 %m월 %d일")

            context.user_data['date'] = selected_date

            # 시간 선택기로 이동
            time_markup = create_time_selector()
            await query.edit_message_text(f"📅 {date_text} 선택됨\n출발 시간을 선택해주세요:", reply_markup=time_markup)

        # 시간 관련 콜백
        elif choice.startswith("time_"):
            if choice.startswith("time_hour_"):
                hour = int(choice.split("_")[2])
                context.user_data['selected_hour'] = hour
                # 분 선택 유지하면서 시간 업데이트
                selected_minute = context.user_data.get('selected_minute')
                time_markup = create_time_selector(hour, selected_minute)
                await query.edit_message_reply_markup(reply_markup=time_markup)

            elif choice.startswith("time_minute_"):
                minute = int(choice.split("_")[2])
                context.user_data['selected_minute'] = minute
                # 시간 선택 유지하면서 분 업데이트
                selected_hour = context.user_data.get('selected_hour')
                time_markup = create_time_selector(selected_hour, minute)
                await query.edit_message_reply_markup(reply_markup=time_markup)

            elif choice == "time_confirm":
                selected_hour = context.user_data.get('selected_hour')
                selected_minute = context.user_data.get('selected_minute')

                if selected_hour is not None and selected_minute is not None:
                    time_str = f"{selected_hour:02d}{selected_minute:02d}00"
                    context.user_data['time'] = time_str

                    await query.edit_message_text(f"🕐 {selected_hour:02d}:{selected_minute:02d} 선택됨\n\n🔍 열차를 검색합니다...")

                    # 열차 검색 및 표시
                    dep = context.user_data.get('departure')
                    arr = context.user_data.get('destination')
                    date = context.user_data.get('date')
                    service = context.user_data.get('service')

                    if all([dep, arr, date, service]):
                        await train_reservation.search_and_show_trains(
                            dep, arr, date, time_str, service,
                            update.effective_chat.id, context
                        )
                    else:
                        await query.edit_message_text("❌ 검색 정보가 부족합니다. 다시 시도해주세요.")
                else:
                    await query.answer("시간과 분을 모두 선택해주세요!")

            elif choice == "time_reset":
                # 시간 선택 초기화
                if 'selected_hour' in context.user_data:
                    del context.user_data['selected_hour']
                if 'selected_minute' in context.user_data:
                    del context.user_data['selected_minute']
                time_markup = create_time_selector()
                await query.edit_message_reply_markup(reply_markup=time_markup)

            elif choice == "time_cancel":
                await query.edit_message_text("시간 선택이 취소되었습니다. 다시 시도해주세요.")

        # 빠른 경로 관련 콜백
        elif choice.startswith("route_"):
            if choice == "route_ktx_seoul_busan":
                context.user_data['departure'] = '서울'
                context.user_data['destination'] = '부산'
                context.user_data['service'] = 'KTX'
                calendar_markup = create_calendar()
                await query.edit_message_text('🚄 KTX: 서울 → 부산\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)

            elif choice == "route_ktx_busan_seoul":
                context.user_data['departure'] = '부산'
                context.user_data['destination'] = '서울'
                context.user_data['service'] = 'KTX'
                calendar_markup = create_calendar()
                await query.edit_message_text('🚄 KTX: 부산 → 서울\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)

            elif choice == "route_seoul_busan":
                context.user_data['departure'] = '수서'  # SRT는 수서역에서 출발
                context.user_data['destination'] = '부산'
                context.user_data['service'] = 'SRT'
                calendar_markup = create_calendar()
                await query.edit_message_text('🚄 SRT: 서울(수서) → 부산\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)

            elif choice == "route_busan_seoul":
                context.user_data['departure'] = '부산'
                context.user_data['destination'] = '수서'  # SRT는 수서역으로 도착
                context.user_data['service'] = 'SRT'
                calendar_markup = create_calendar()
                await query.edit_message_text('🚄 SRT: 부산 → 서울(수서)\n여행 날짜를 선택해주세요:', reply_markup=calendar_markup)

            elif choice == "route_custom":
                await query.edit_message_text("직접 입력 방식을 선택하셨습니다.\n출발지를 입력해주세요:")
                return DEPARTURE

        # 열차 선택 콜백
        elif choice.startswith("select_train_"):
            train_index = int(choice.split("_")[2])
            available_trains = context.user_data.get('available_trains', [])

            if 0 <= train_index < len(available_trains):
                selected_train_info = available_trains[train_index]
                context.user_data['selected_train'] = selected_train_info['train']
                context.user_data['selected_train_info'] = selected_train_info

                await query.edit_message_text(f"✅ 선택된 열차:\n{selected_train_info['display_text']}\n\n이제 인원수를 선택해주세요:")

                # 인원수 선택으로 진행
                await train_reservation.ask_passenger_count(update, context)
            else:
                await query.answer("잘못된 열차 선택입니다.")

        # 정렬 옵션 콜백
        elif choice == "sort_time":
            # 시간순 정렬 (이미 구현되어 있음)
            await query.answer("이미 시간순으로 정렬되어 있습니다.")

        elif choice == "sort_price":
            # 가격순 정렬 (추후 구현)
            await query.answer("가격순 정렬은 추후 지원 예정입니다.")

        elif choice == "search_again":
            # 다시 검색
            dep = context.user_data.get('departure')
            arr = context.user_data.get('destination')
            date = context.user_data.get('date')
            time = context.user_data.get('time')
            service = context.user_data.get('service')

            if all([dep, arr, date, time, service]):
                await query.edit_message_text("🔄 열차를 다시 검색합니다...")
                await train_reservation.search_and_show_trains(dep, arr, date, time, service, update.effective_chat.id, context)
            else:
                await query.answer("검색 정보가 부족합니다.")

        # 다중/단일 모드 선택 콜백
        elif choice == "multi_monitor_mode":
            # 다중 모니터링 모드로 전환
            available_trains = context.user_data.get('available_trains', [])
            if not available_trains:
                await query.answer("열차 정보가 없습니다. 다시 검색해주세요.")
                return

            # 다중 모니터링을 위한 열차 선택 UI로 변경
            train_list_text = "🎯 다중 모니터링 모드\n\n원하는 열차들을 선택하세요 (여러 개 선택 가능):\n\n"

            dep = context.user_data.get('departure')
            arr = context.user_data.get('destination')
            date = context.user_data.get('date')
            service = context.user_data.get('service')

            for i, train_info in enumerate(available_trains):
                train_list_text += f"[{i+1}] {train_info['display_text'].replace(chr(10), ' | ')}\n\n"

            # 체크박스 스타일 버튼들
            keyboard = []
            context.user_data['selected_for_multi'] = context.user_data.get('selected_for_multi', set())

            row = []
            for i in range(len(available_trains)):
                selected = i in context.user_data['selected_for_multi']
                button_text = f"✅ {i+1}번" if selected else f"☐ {i+1}번"
                row.append(InlineKeyboardButton(button_text, callback_data=f"multi_toggle_{i}"))
                if len(row) == 3:  # 3열로 배치
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            # 하단 버튼들
            keyboard.append([
                InlineKeyboardButton("✅ 선택완료 (모니터링 시작)", callback_data="multi_start"),
                InlineKeyboardButton("🔙 단일 모드로", callback_data="single_booking_mode")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(train_list_text, reply_markup=reply_markup)

        elif choice == "single_booking_mode":
            # 단일 예매 모드 (기존 방식)
            available_trains = context.user_data.get('available_trains', [])
            if not available_trains:
                await query.answer("열차 정보가 없습니다. 다시 검색해주세요.")
                return

            train_list_text = "🎫 단일 예매 모드\n\n예매할 열차를 1개 선택하세요:\n\n"

            for i, train_info in enumerate(available_trains):
                train_list_text += f"[{i+1}] {train_info['display_text'].replace(chr(10), ' | ')}\n\n"

            # 단일 선택 버튼들
            keyboard = []
            row = []
            for i in range(len(available_trains)):
                row.append(InlineKeyboardButton(f"{i+1}번", callback_data=f"select_train_{i}"))
                if len(row) == 4:  # 4열로 배치
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            keyboard.append([InlineKeyboardButton("🎯 다중 모드로", callback_data="multi_monitor_mode")])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(train_list_text, reply_markup=reply_markup)

        # 다중 모니터링 체크박스 토글
        elif choice.startswith("multi_toggle_"):
            train_index = int(choice.split("_")[2])
            selected_set = context.user_data.get('selected_for_multi', set())

            if train_index in selected_set:
                selected_set.remove(train_index)
            else:
                selected_set.add(train_index)

            context.user_data['selected_for_multi'] = selected_set

            # UI 업데이트
            available_trains = context.user_data.get('available_trains', [])
            train_list_text = "🎯 다중 모니터링 모드\n\n원하는 열차들을 선택하세요 (여러 개 선택 가능):\n\n"

            for i, train_info in enumerate(available_trains):
                train_list_text += f"[{i+1}] {train_info['display_text'].replace(chr(10), ' | ')}\n\n"

            # 체크박스 스타일 버튼들 업데이트
            keyboard = []
            row = []
            for i in range(len(available_trains)):
                selected = i in selected_set
                button_text = f"✅ {i+1}번" if selected else f"☐ {i+1}번"
                row.append(InlineKeyboardButton(button_text, callback_data=f"multi_toggle_{i}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            # 하단 버튼들
            start_text = f"✅ 선택완료 ({len(selected_set)}개 모니터링 시작)" if selected_set else "✅ 선택완료 (모니터링 시작)"
            keyboard.append([
                InlineKeyboardButton(start_text, callback_data="multi_start"),
                InlineKeyboardButton("🔙 단일 모드로", callback_data="single_booking_mode")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_reply_markup(reply_markup=reply_markup)

        elif choice == "multi_start":
            # 다중 모니터링 시작
            selected_set = context.user_data.get('selected_for_multi', set())
            available_trains = context.user_data.get('available_trains', [])

            if not selected_set:
                await query.answer("먼저 모니터링할 열차를 선택해주세요.")
                return

            # 선택된 열차들로 다중 타겟 생성
            chat_id = update.effective_chat.id
            dep = context.user_data.get('departure')
            arr = context.user_data.get('destination')
            date = context.user_data.get('date')
            service = context.user_data.get('service')

            courses = []
            for i, train_index in enumerate(sorted(selected_set)):
                try:
                    if train_index < len(available_trains):
                        train_info = available_trains[train_index]
                        train = train_info.get('train')

                        # 열차 시간 추출 - 더 안전한 방식
                        dep_time = "060000"  # 기본값

                        if train and hasattr(train, 'dep_time') and train.dep_time:
                            try:
                                dep_time = train.dep_time.strftime('%H%M%S')
                            except Exception as time_err:
                                logger.warning(f"시간 변환 실패: {time_err}")

                        # 시간이 여전히 기본값이면 display_text에서 추출 시도
                        if dep_time == "060000" and 'display_text' in train_info:
                            try:
                                # display_text에서 시간 패턴 찾기 (예: "08:00" 형태)
                                import re
                                time_match = re.search(r'(\d{1,2}):(\d{2})', train_info['display_text'])
                                if time_match:
                                    hour = time_match.group(1).zfill(2)
                                    minute = time_match.group(2)
                                    dep_time = f"{hour}{minute}00"
                                    logger.info(f"Display text에서 시간 추출: {dep_time}")
                            except Exception as extract_err:
                                logger.warning(f"Display text 시간 추출 실패: {extract_err}")

                        course = {
                            'service': service,
                            'departure': dep,
                            'arrival': arr,
                            'date': date,
                            'time': dep_time,
                            'priority': i + 1,
                            'scan_only': True,
                            'metadata': {'train_info': train_info}
                        }

                        courses.append(course)
                        logger.info(f"다중 코스 {i+1} 추가: {dep}→{arr} {dep_time} ({service})")

                except Exception as course_err:
                    logger.error(f"코스 {i+1} 처리 중 오류: {course_err}")
                    continue

            if courses:
                # 타겟 그룹 추가
                targets = await target_registry.add_target_group(
                    chat_id=chat_id,
                    targets_data=courses
                )

                group_id = targets[0].group_id if targets else "unknown"

                message_text = (
                    f"🎯 다중 모니터링 시작!\n\n"
                    f"📋 등록된 열차: {len(courses)}개\n"
                    f"🆔 그룹 ID: {group_id[:8]}...\n"
                    f"🔍 모니터링 중... 표가 나오면 우선순위에 따라 자동 예매됩니다.\n\n"
                    f"📊 상태 확인: /multi_status\n"
                    f"🛑 중단: /stop_multi"
                )

                await query.edit_message_text(message_text)
            else:
                await query.answer("열차 정보 처리 중 오류가 발생했습니다.")

        # 인원수 선택 콜백
        elif choice.startswith("adult_"):
            if choice == "adult_manual":
                await query.edit_message_text("어른 인원수를 숫자로 입력해주세요:")
                context.user_data['expect_input'] = 'adult_count'
                return
            else:
                adult_count = int(choice.split("_")[1])
                context.user_data['adult_count'] = adult_count
                await query.edit_message_text(f"어른 {adult_count}명 선택됨")
                # 어린이 수 선택으로 진행
                await train_reservation.ask_child_count(update, context)

        elif choice.startswith("child_"):
            if choice == "child_manual":
                await query.edit_message_text("어린이 인원수를 숫자로 입력해주세요:")
                context.user_data['expect_input'] = 'child_count'
                return
            else:
                child_count = int(choice.split("_")[1])
                context.user_data['child_count'] = child_count
                await query.edit_message_text(f"어린이 {child_count}명 선택됨")
                # 창가 자리 선택으로 진행
                await train_reservation.ask_window_seat(update, context)

        # 기존 창가/좌석 선택 콜백
        elif choice in ["window_priority", "window_only", "window_no"]:
            # 창가 자리 선택 처리
            if choice == "window_priority":
                context.user_data['window_seat'] = True
                context.user_data['window_only'] = False
                reply_text = "창가 우선으로 설정되었습니다."
            elif choice == "window_only":
                context.user_data['window_seat'] = True
                context.user_data['window_only'] = True
                reply_text = "창가만으로 설정되었습니다."
            else:  # window_no
                context.user_data['window_seat'] = False
                context.user_data['window_only'] = False
                reply_text = "좌석 무관으로 설정되었습니다."

            await query.edit_message_text(reply_text)
            # 좌석 타입 선택 요청
            await train_reservation.ask_seat_type(update, context)
        elif choice in ["seat_special", "seat_general"]:
            # 좌석 타입 선택 처리
            if choice == "seat_special":
                context.user_data['seat_type'] = SeatType.SPECIAL_ONLY
                reply_text = "특실로 예약을 시도합니다."
            else:
                context.user_data['seat_type'] = SeatType.GENERAL_ONLY
                reply_text = "일반실로 예약을 시도합니다."

            await query.edit_message_text(reply_text)

            # 모든 정보 수집 완료, 예약 시작
            await update.callback_query.message.reply_text('예약을 시작합니다. 중단하려면 /stop 명령어를 사용하세요.')

            # 선택된 열차로 예약 진행
            selected_train = context.user_data.get('selected_train')
            if selected_train:
                # 선택된 열차 정보로 예약
                train_reservation.reserve_selected_train(
                    selected_train,
                    context.user_data,
                    update.effective_chat.id,
                    context
                )
            else:
                # 기존 방식으로 예약 (하위 호환성)
                train_reservation.search_and_reserve(
                    context.user_data['departure'],
                    context.user_data['destination'],
                    context.user_data['date'],
                    context.user_data['time'],
                    context.user_data['service'],
                    update.effective_chat.id,
                    context
                )
        else:
            await query.answer()
    
    # 메시지 핸들러와 콜백 쿼리 핸들러 등록
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    application.add_handler(CallbackQueryHandler(handle_callback_query))

    # 높은 우선순위로 stop, status 핸들러 다시 등록
    application.add_handler(CommandHandler('stop', stop), group=1)
    application.add_handler(CommandHandler('status', status), group=1)

    # 파이프라인에 봇 연결
    reservation_executor.bind_bot(application.bot)

    # 파이프라인 시작
    logger.info("파이프라인 워커 시작...")
    scanner_worker.start(loop)
    reservation_executor.start(loop)

    try:
        application.run_polling()
    finally:
        # 파이프라인 정리
        logger.info("파이프라인 워커 정리 중...")
        loop.create_task(scanner_worker.stop())
        loop.create_task(reservation_executor.stop())

if __name__ == '__main__':
    main()





