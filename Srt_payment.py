import os
import logging
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException, TimeoutException, NoSuchElementException
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('srt_payment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 환경 변수는 main2.py에서 로드됨

# 환경변수에서 로그인 및 카드 정보 가져오기
srt_user = os.getenv("SRT_USER_num")
srt_pass = os.getenv("SRT_PASS")
card_num1 = os.getenv("Card_Num1_korail")
card_num2 = os.getenv("Card_Num2_korail")
card_num3 = os.getenv("Card_Num3_korail")
card_num4 = os.getenv("Card_Num4_korail")
card_num5 = os.getenv("Card_Num5_korail")
id_num1 = os.getenv("Id_Num1_korail")

# Chrome 옵션 설정
chrome_options = Options()
chrome_options.add_argument('--start-maximized')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-dev-shm-usage')
chrome_options.add_argument('--disable-blink-features=AutomationControlled')
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)
# User-Agent 추가
chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
# chrome_options.add_argument('--headless')  # GUI 없이 실행하려면 이 옵션 추가

# WebDriver 초기화
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=chrome_options)

def handle_popups(driver, close_btn_selector=".popup_close_btn", wait_time=10):
    """
    코레일 홈페이지 접근 시 발생하는 팝업(새 창/탭, JS Alert, 레이어 팝업)을 처리하는 함수.
    """
    # (A) 새 창/탭 형태 팝업 처리
    main_handle = driver.current_window_handle
    for handle in driver.window_handles:
        if handle != main_handle:
            driver.switch_to.window(handle)
            driver.close()
    # 메인창으로 복귀
    driver.switch_to.window(main_handle)

    # (B) JS Alert/Confirm 팝업 처리
    try:
        alert = driver.switch_to.alert
        alert.accept()  # '확인' 클릭
    except NoAlertPresentException:
        pass

    # (C) 페이지 내 레이어 팝업(모달, 배너) 처리
    try:
        close_button = WebDriverWait(driver, wait_time).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, close_btn_selector))
        )
        close_button.click()
    except TimeoutException:
        pass

def safe_select_option(select_element, select_type, value):
    """
    드롭다운 메뉴에서 옵션을 안전하게 선택하는 함수
    
    Args:
        select_element: Select 요소
        select_type: 선택 방식 ('value', 'text', 'index')
        value: 선택하고자 하는 값
    """
    options = [option.get_attribute('value') for option in select_element.options]
    print(f"드롭다운에서 사용 가능한 옵션들: {options}")
    
    if select_type == 'value':
        # 2027년을 입력했다면 '27'을 찾아야 함
        short_year = str(value)[-2:]  # 2027 -> '27'
        
        if short_year in options:
            print(f"선택된 연도: {short_year}")
            select_element.select_by_value(short_year)
        else:
            # 가능한 연도 중에서 가장 가까운 것을 선택
            valid_years = [year for year in options if year.isdigit()]
            if valid_years:
                closest_year = min(valid_years, key=lambda x: abs(int(x) - int(short_year)))
                print(f"입력한 연도 {short_year}가 없어 가장 가까운 연도 {closest_year} 선택")
                select_element.select_by_value(closest_year)
            else:
                raise ValueError(f"선택 가능한 연도가 없습니다. 사용 가능한 옵션: {options}")

# Add this function at the beginning of your code with other function definitions
def handle_srt_app_alert(driver, timeout=5):
    """
    Handles the SRT app installation confirmation alert.
    Returns True if alert was found and handled, False otherwise.
    """
    try:
        # Wait for alert to be present
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert_text = alert.text
        print(f"알림창 감지: {alert_text}")
        alert.accept()
        print("알림창 확인 버튼 클릭 완료")
        return True
    except TimeoutException:
        print("알림창이 나타나지 않았습니다.")
        return False

try:
    # SRT 홈페이지 접속
    logger.info("SRT 홈페이지 접속 시작")
    driver.get("https://etk.srail.kr/main.do")
    time.sleep(5)
    logger.info(f"현재 URL: {driver.current_url}")

    handle_popups(driver)
    time.sleep(2)  # 팝업 제거 대기

    # 로그인 버튼 클릭
    try:
        login_button = driver.find_element(By.XPATH, "/html/body/div[1]/div[3]/div[1]/div/a[2]")
        logger.info("로그인 버튼 클릭")
        login_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"로그인 버튼을 찾을 수 없음: {str(e)}")
        raise

    # 로그인 정보 입력
    try:
        username = driver.find_element(By.XPATH, "/html/body/div/div[4]/div/div[2]/form/fieldset/div[1]/div[1]/div[2]/div/div[1]/div[1]/input")
        password = driver.find_element(By.XPATH, "/html/body/div/div[4]/div/div[2]/form/fieldset/div[1]/div[1]/div[2]/div/div[1]/div[2]/input")

        logger.info(f"아이디 입력: {srt_user}")
        username.send_keys(srt_user)
        logger.info("비밀번호 입력")
        password.send_keys(srt_pass)
    except NoSuchElementException as e:
        logger.error(f"로그인 입력 필드를 찾을 수 없음: {str(e)}")
        raise

    # 로그인 버튼 클릭
    try:
        login_submit = driver.find_element(By.XPATH, "/html/body/div/div[4]/div/div[2]/form/fieldset/div[1]/div[1]/div[2]/div/div[2]/input")
        logger.info("로그인 제출 버튼 클릭")
        login_submit.click()
        time.sleep(5)
    except NoSuchElementException as e:
        logger.error(f"로그인 제출 버튼을 찾을 수 없음: {str(e)}")
        raise

    logger.info("로그인 시도 중...")
    handle_popups(driver)
    time.sleep(2)  # 팝업 제거 대기
    logger.info(f"로그인 후 URL: {driver.current_url}")

    # 예매하기 버튼 클릭
    try:
        booking_button = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div[1]/div[2]/div[1]/div[2]/ul/li[1]/a/img")
        logger.info("예매하기 버튼 클릭")
        booking_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"예매하기 버튼을 찾을 수 없음: {str(e)}")
        raise

    # 조회하기 버튼 클릭
    try:
        search_button = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div/div[4]/form/fieldset/div/table/tbody/tr/td[10]/a")
        logger.info("조회하기 버튼 클릭")
        search_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"조회하기 버튼을 찾을 수 없음: {str(e)}")
        raise

    # 예매하기 버튼 클릭
    try:
        reserve_button = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div/div[2]/form/fieldset/div[9]/button[1]")
        logger.info("예매하기 버튼 클릭")
        reserve_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"예매하기 버튼을 찾을 수 없음: {str(e)}")
        raise

    #카드번호 보안키패드 해제
    try:
        secu_button1 = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div/div[2]/form/fieldset/div[5]/div[1]/table/tbody/tr[2]/td/span/input")
        logger.info("카드번호 보안키패드 해제")
        secu_button1.click()
        time.sleep(1)
    except NoSuchElementException as e:
        logger.error(f"보안키패드 해제 버튼을 찾을 수 없음: {str(e)}")
        raise

    # 카드 정보 입력
    logger.info("카드 번호 입력 시작")
    card_inputs = {
        "stlCrCrdNo11": card_num1,
        "stlCrCrdNo12": card_num2,
        "stlCrCrdNo13": card_num3,
        "stlCrCrdNo14": card_num4
    }

    for input_id, value in card_inputs.items():
        try:
            card_input = driver.find_element(By.ID, input_id)
            card_input.send_keys(value)
            logger.info(f"카드 번호 입력: {input_id}")
            time.sleep(0.5)
        except NoSuchElementException as e:
            logger.error(f"카드 입력 필드를 찾을 수 없음: {input_id}, {str(e)}")
            raise

    # 카드 유효기간 선택 부분
    try:
        logger.info("카드 유효기간 선택 시작")
        # 환경 변수에서 카드 만료 월과 연도 가져오기
        card_expiry_month = os.getenv("CARD_MONTH")
        card_expiry_year = os.getenv("CARD_YEAR")

        # 월 선택
        month_select = Select(driver.find_element(By.ID, "crdVlidTrm1M"))
        month_select.select_by_value(card_expiry_month)  # 환경 변수 사용
        logger.info(f"카드 유효월 선택: {card_expiry_month}")
        time.sleep(0.5)

        # 연도 선택
        year_select = Select(driver.find_element(By.ID, "crdVlidTrm1Y"))
        safe_select_option(year_select, 'value', card_expiry_year)  # 환경 변수 사용
        logger.info(f"카드 유효년도 선택: {card_expiry_year}")
        time.sleep(0.5)

    except Exception as e:
        logger.error(f"드롭다운 선택 중 오류 발생: {str(e)}")
        raise

    #법인카드 선택
    try:
        card_select = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div/div[2]/form/fieldset/div[5]/div[1]/table/tbody/tr[1]/td/div/input[2]")
        logger.info("법인카드 선택")
        card_select.click()
        time.sleep(1)
    except NoSuchElementException as e:
        logger.error(f"법인카드 선택 버튼을 찾을 수 없음: {str(e)}")
        raise

    # 카드 비밀번호 및 생년월일 입력
    try:
        secu_button2 = driver.find_element(By.XPATH, "/html/body/div[1]/div[4]/div/div[2]/form/fieldset/div[5]/div[1]/table/tbody/tr[5]/td/span[1]/input")
        logger.info("보안 입력 필드 활성화")
        secu_button2.click()
        time.sleep(1)

        pwd_input = driver.find_element(By.ID, "vanPwd1")
        pwd_input.send_keys(card_num5)
        logger.info("카드 비밀번호 입력 완료")
        time.sleep(0.5)

        birth_input = driver.find_element(By.ID, "athnVal1")
        birth_input.send_keys(id_num1)
        logger.info("생년월일 입력 완료")
        time.sleep(0.5)
    except NoSuchElementException as e:
        logger.error(f"비밀번호/생년월일 입력 필드를 찾을 수 없음: {str(e)}")
        raise

    # 결제하기 버튼 클릭
    try:
        payment_button = driver.find_element(By.XPATH, '//*[@id="select-form"]/fieldset/div[11]/div[2]/ul/li[2]/a')
        logger.info("결제하기 버튼 클릭")
        payment_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"결제하기 버튼을 찾을 수 없음: {str(e)}")
        raise

    # SRT 앱 설치 확인 알림창 처리
    handle_srt_app_alert(driver)
    time.sleep(1)

    # 발행요청 버튼 클릭
    try:
        issue_button = driver.find_element(By.ID, "requestIssue1")
        logger.info("발행요청 버튼 클릭")
        issue_button.click()
        time.sleep(2)
    except NoSuchElementException as e:
        logger.error(f"발행요청 버튼을 찾을 수 없음: {str(e)}")
        raise

    # SRT 앱 설치 확인 알림창 처리
    handle_srt_app_alert(driver)
    time.sleep(1)
    logger.info("결제 프로세스 완료")

except Exception as e:
    logger.error(f"결제 프로세스 중 치명적 오류 발생: {str(e)}")
    # 스크린샷 저장 시도
    try:
        screenshot_path = f"srt_error_{int(time.time())}.png"
        driver.save_screenshot(screenshot_path)
        logger.info(f"오류 스크린샷 저장: {screenshot_path}")
    except:
        logger.warning("스크린샷 저장 실패")
    # 예외 발생 시 알림창 처리 시도
    try:
        alert = driver.switch_to.alert
        alert.accept()
        logger.info("예외 처리 중 알림창 확인")
    except:
        pass
    raise

finally:
    logger.info("결제 프로세스 완료, 브라우저 종료")
    time.sleep(3)
    try:
        driver.quit()
        logger.info("SRT 결제 스크립트 종료")
    except:
        logger.warning("브라우저 종료 중 오류 발생")