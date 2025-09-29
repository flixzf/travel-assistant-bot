import os
import logging
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoAlertPresentException, TimeoutException, NoSuchElementException, ElementClickInterceptedException
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
        logging.FileHandler('korail_payment.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 환경 변수는 main2.py에서 로드됨

# Chrome 옵션 설정 (서버 환경 대응)
chrome_options = Options()

# 서버 환경 감지
is_server = os.getenv('RENDER') or os.getenv('HEROKU') or os.getenv('DOCKER')

if is_server:
    # 서버 환경용 Chrome 옵션
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--disable-plugins')
else:
    # 로컬 환경용 Chrome 옵션
    chrome_options.add_argument('--start-maximized')
    # chrome_options.add_argument('--headless')  # 로컬에서 GUI 없이 실행하려면 주석 해제

# 환경변수에서 로그인 정보 가져오기
korail_user = os.getenv("KORAIL_USER")
korail_pass = os.getenv("KORAIL_PASS")
korail_pass_bank = os.getenv("KORAIL_PASS_BANK")  # 6자리 숫자 (예: "123456")
Card_Num1_korail = os.getenv("Card_Num1_korail")
Card_Num2_korail = os.getenv("Card_Num2_korail")
Card_Num3_korail = os.getenv("Card_Num3_korail")
Card_Num4_korail = os.getenv("Card_Num4_korail")
Card_Num5_korail = os.getenv("Card_Num5_korail")
Id_Num1_korail = os.getenv("Id_Num1_korail")


# WebDriver 초기화
logger.info("Chrome WebDriver 초기화")
try:
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    logger.info("WebDriver 초기화 성공")
except Exception as e:
    logger.error(f"WebDriver 초기화 실패: {str(e)}")
    raise

def handle_popups(driver, close_btn_selector=".popup_close_btn", wait_time=10):
    """
    코레일 홈페이지 접근 시 발생하는 팝업(새 창/탭, JS Alert, 레이어 팝업)을 처리하는 함수.
    """
    logger.info("팝업 처리 시작")

    # (A) 새 창/탭 형태 팝업 처리
    main_handle = driver.current_window_handle
    popup_count = 0
    for handle in driver.window_handles:
        if handle != main_handle:
            driver.switch_to.window(handle)
            logger.info(f"팝업 창 닫기: {handle}")
            driver.close()
            popup_count += 1
    # 메인창으로 복귀
    driver.switch_to.window(main_handle)
    if popup_count > 0:
        logger.info(f"총 {popup_count}개의 팝업 창 닫음")

    # (B) JS Alert/Confirm 팝업 처리
    try:
        alert = driver.switch_to.alert
        alert_text = alert.text
        logger.info(f"알림창 감지 및 확인: {alert_text}")
        alert.accept()  # '확인' 클릭
    except NoAlertPresentException:
        logger.debug("알림창 없음")
    except Exception as e:
        logger.warning(f"알림창 처리 중 오류: {str(e)}")

    # (C) React 모달 오버레이 처리
    try:
        # React 모달 오버레이 확인 및 제거
        react_modals = driver.find_elements(By.CSS_SELECTOR, ".ReactModal__Overlay")
        if react_modals:
            logger.info(f"React 모달 {len(react_modals)}개 발견, 제거 시도")
            driver.execute_script("""
                var modals = document.querySelectorAll('.ReactModal__Overlay');
                modals.forEach(function(modal) {
                    modal.style.display = 'none';
                    modal.remove();
                });
            """)
            time.sleep(0.5)
            logger.info("React 모달 제거 완료")
        else:
            logger.debug("React 모달 없음")
    except Exception as e:
        logger.warning(f"React 모달 처리 중 오류: {str(e)}")

    # (D) 페이지 내 레이어 팝업(모달, 배너) 처리
    try:
        close_button = WebDriverWait(driver, wait_time).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, close_btn_selector))
        )
        logger.info(f"닫기 버튼 클릭: {close_btn_selector}")
        close_button.click()
    except TimeoutException:
        logger.debug(f"닫기 버튼 없음: {close_btn_selector}")
    except Exception as e:
        logger.warning(f"닫기 버튼 처리 중 오류: {str(e)}")

    logger.info("팝업 처리 완료")

def must_accept_alert(driver):
    """
    Alert가 반드시 있어야 하며 '확인'을 눌러야 하는 상황일 때 사용.
    Alert가 없으면 예외 발생.
    """
    try:
        alert = driver.switch_to.alert
        alert.accept()  # '확인' 클릭
    except NoAlertPresentException:
        print("예상했던 Alert가 나타나지 않았습니다.")
        raise  # 필요시 예외 발생으로 코드 중단
    
# 팝업 창 처리를 위한 함수 수정
def handle_popup_window(driver, main_handle, action_function):
    """
    팝업 창을 안전하게 처리하는 함수
    
    Parameters:
    - driver: WebDriver 인스턴스
    - main_handle: 메인 창의 핸들
    - action_function: 팝업 창에서 수행할 동작을 담은 함수
    """
    try:
        # 팝업 창이 열릴 때까지 대기
        WebDriverWait(driver, 10).until(lambda d: len(d.window_handles) > 1)
        
        # 새 팝업 창 찾기
        popup_handle = None
        for handle in driver.window_handles:
            if handle != main_handle:
                popup_handle = handle
                break
        
        if popup_handle:
            # 팝업 창으로 전환
            driver.switch_to.window(popup_handle)
            
            # 팝업 창에서 동작 수행
            action_function(driver)
            
            # 팝업 창이 아직 존재하는지 확인 후 닫기
            if popup_handle in driver.window_handles:
                driver.close()
            
            # 메인 창으로 돌아가기
            driver.switch_to.window(main_handle)
            
    except Exception as e:
        print(f"팝업 창 처리 중 오류 발생: {str(e)}")
        # 메인 창으로 돌아가기 시도
        if main_handle in driver.window_handles:
            driver.switch_to.window(main_handle)
        raise

# 코레일 홈페이지 접속
logger.info("코레일 홈페이지 접속 시작")
driver.get("https://info.korail.com/info/index.do?null")
time.sleep(2)  # 페이지 로딩 대기
logger.info(f"현재 URL: {driver.current_url}")

handle_popups(driver)
time.sleep(2)  # 팝업 제거 대기

# 로그인 페이지로 이동하는 이미지 클릭
try:
    login_image = driver.find_element(By.XPATH, "/html/body/div[2]/header/div[2]/div/div[2]/ul/li[1]/a")
    logger.info("로그인 링크 클릭")
    login_image.click()
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"로그인 링크를 찾을 수 없음: {str(e)}")
    raise

# 회원번호 클릭
try:
    member_number = driver.find_element(By.XPATH, "//*[@id='wrapper']/div/div/div[2]/div/div[1]/div[1]/div/form/ul/li[2]/button")
    logger.info("회원번호 로그인 방식 선택")
    member_number.click()
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"회원번호 버튼을 찾을 수 없음: {str(e)}")
    raise

# 아이디/비밀번호 입력
try:
    userid_input = driver.find_element(By.XPATH, "//*[@id='txtMember']")
    password_input = driver.find_element(By.XPATH, "//*[@id='txtPwd']")

    logger.info(f"아이디 입력: {korail_user}")
    userid_input.send_keys(korail_user)
    logger.info("비밀번호 입력")
    password_input.send_keys(korail_pass)
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"로그인 입력 필드를 찾을 수 없음: {str(e)}")
    raise

# 로그인 버튼 클릭
try:
    login_button = driver.find_element(By.XPATH, "/html/body/div/div/div/div[2]/div/div[1]/div[1]/div/form/div[2]/fieldset/input")
    logger.info("로그인 버튼 클릭")
    time.sleep(2)
    login_button.click()
except NoSuchElementException as e:
    logger.error(f"로그인 버튼을 찾을 수 없음: {str(e)}")
    raise

logger.info("로그인 시도 중...")
time.sleep(2)  # 로그인 대기
handle_popups(driver)
time.sleep(2)  # 팝업 제거 대기
logger.info(f"로그인 후 URL: {driver.current_url}")

# 예매 리스트 페이지가 이미 열려 있다면 새로 고침, 그렇지 않으면 해당 페이지로 이동합니다.
expected_url = "https://www.korail.com/ticket/reservation/list#"
logger.info(f"예상 URL: {expected_url}")
logger.info(f"현재 URL: {driver.current_url}")

if driver.current_url != expected_url:
    logger.info("예매 리스트 페이지로 이동")
    driver.get(expected_url)
else:
    logger.info("예매 리스트 페이지 새로고침")
    driver.refresh()
time.sleep(2)
handle_popups(driver)

# 발권
logger.info("발권 프로세스 시작")
handle_popups(driver)

# 모달이 완전히 사라질 때까지 대기
try:
    # 모달 오버레이가 사라질 때까지 대기 (최대 10초)
    WebDriverWait(driver, 10).until_not(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".ReactModal__Overlay"))
    )
    logger.info("모달 오버레이 사라짐")
except TimeoutException:
    # 모달이 여전히 있다면 JavaScript로 강제 제거
    logger.warning("모달 오버레이가 사라지지 않아 강제 제거 시도")
    driver.execute_script("""
        var modals = document.querySelectorAll('.ReactModal__Overlay');
        modals.forEach(function(modal) {
            modal.style.display = 'none';
            modal.remove();
        });
    """)
    time.sleep(1)

# 발권 버튼이 클릭 가능할 때까지 대기 (여러 선택자 시도)
try:
    logger.info("발권 버튼 대기 중...")

    # 여러 가능한 발권 버튼 선택자들
    button_selectors = [
        "//button[contains(text(), '발권')]",
        "//button[contains(text(), '승차권 발급')]",
        "//button[contains(text(), '티켓 발급')]",
        "//*[@id='container']//button[3]",
        "//*[@id='container']/div/div[2]/div/ul/li/div/div[2]/div/div/button[3]",
        "//button[contains(@class, 'btn') and contains(text(), '발권')]"
    ]

    step1 = None
    for selector in button_selectors:
        try:
            logger.info(f"발권 버튼 찾는 중: {selector}")
            step1 = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, selector))
            )
            logger.info(f"발권 버튼 발견: {selector}")
            break
        except:
            continue

    if step1:
        logger.info("발권 버튼 클릭")
        step1.click()
        time.sleep(2)
        handle_popups(driver)
    else:
        # 페이지 소스 로깅 (디버깅용)
        logger.error("발권 버튼을 찾을 수 없음. 현재 페이지 정보:")
        logger.error(f"현재 URL: {driver.current_url}")
        logger.error(f"페이지 제목: {driver.title}")

        # 페이지에 있는 모든 버튼 로깅
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            logger.error(f"페이지에서 발견된 버튼 수: {len(buttons)}")
            for i, btn in enumerate(buttons[:10]):  # 최대 10개만 로깅
                try:
                    btn_text = btn.text.strip()
                    btn_id = btn.get_attribute("id")
                    btn_class = btn.get_attribute("class")
                    logger.error(f"버튼 {i+1}: 텍스트='{btn_text}', ID='{btn_id}', 클래스='{btn_class}'")
                except:
                    pass
        except:
            pass

        raise Exception("모든 발권 버튼 선택자로 버튼을 찾을 수 없음")
except TimeoutException as e:
    logger.error(f"발권 버튼을 찾을 수 없음: {str(e)}")
    raise

# 카드 결제 클릭
logger.info("카드 결제 선택")
handle_popups(driver)

# 카드 결제 버튼이 클릭 가능할 때까지 대기
try:
    logger.info("카드 결제 버튼 대기 중...")
    step2 = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/ul/li[2]/button"))
    )
    logger.info("카드 결제 버튼 클릭")
    step2.click()
    time.sleep(2)
    handle_popups(driver)
except TimeoutException as e:
    logger.error(f"카드 결제 버튼을 찾을 수 없음: {str(e)}")
    raise

# 카드 첫번째 칸 넣기
try:
    logger.info("카드 번호 입력 시작")
    step1 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[2]/div/input[1]")
    step1.click()
    step1.send_keys(Card_Num1_korail)
    logger.info("카드 번호 1번째 자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"카드 번호 1번째 입력 필드를 찾을 수 없음: {str(e)}")
    raise

# 카드 두번째 칸 넣기
try:
    step2 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[2]/div/input[2]")
    step2.click()
    step2.send_keys(Card_Num2_korail)
    logger.info("카드 번호 2번째 자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"카드 번호 2번째 입력 필드를 찾을 수 없음: {str(e)}")
    raise

# 카드 세번째 칸 넣기
try:
    step3 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[2]/div/input[3]")
    step3.click()
    step3.send_keys(Card_Num3_korail)
    logger.info("카드 번호 3번째 자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"카드 번호 3번째 입력 필드를 찾을 수 없음: {str(e)}")
    raise

# 카드 네번째 칸 넣기
try:
    step4 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[2]/div/input[4]")
    step4.click()
    step4.send_keys(Card_Num4_korail)
    logger.info("카드 번호 4번째 자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"카드 번호 4번째 입력 필드를 찾을 수 없음: {str(e)}")
    raise


#유효기간
try:
    logger.info("카드 유효기간 입력 시작")
    step5 = driver.find_element(By.XPATH, "//*[@id='mon03']")
    step5.click()
    # CARD_MONTH is not defined, define it by loading from environment variable
    CARD_MONTH = os.getenv("CARD_MONTH")
    step5.send_keys(CARD_MONTH)
    logger.info(f"카드 유효월 입력: {CARD_MONTH}")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"유효월 입력 필드를 찾을 수 없음: {str(e)}")
    raise

# 유효년도 dropdown 선택: 4번째 옵션 선택
try:
    handle_popups(driver)
    # 드롭다운 요소 클릭하여 열기
    dropdown_year = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[3]/div/select")
    dropdown_year.click()
    logger.info("유효년도 드롭다운 열기")
    time.sleep(1)
    # 4번째 옵션 (option[4]) 선택
    selected_option = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[3]/div/select/option[4]")
    selected_option.click()
    logger.info("유효년도 4번째 옵션 선택")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"유효년도 드롭다운을 찾을 수 없음: {str(e)}")
    raise

#인증번호(주민번호앞자리)
try:
    handle_popups(driver)
    step6 = driver.find_element(By.XPATH, "//*[@id='certi_num']")
    step6.click()
    step6.send_keys(Id_Num1_korail)
    logger.info("주민번호 앞자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"주민번호 입력 필드를 찾을 수 없음: {str(e)}")
    raise

#비번 앞 두자리
try:
    handle_popups(driver)
    step7 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[2]/ul/li[6]/div/input")
    step7.click()
    step7.send_keys(Card_Num5_korail)
    logger.info("카드 비밀번호 앞 두자리 입력 완료")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"카드 비밀번호 입력 필드를 찾을 수 없음: {str(e)}")
    raise

#동의1 클릭
try:
    handle_popups(driver)
    step8 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[1]/div/div[2]/div[2]/div[3]/div/div/label")
    step8.click()
    logger.info("결제 동의 1 클릭")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"결제 동의 1 체크박스를 찾을 수 없음: {str(e)}")
    raise

#동의2 클릭
try:
    handle_popups(driver)
    step9 = driver.find_element(By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[3]/label")
    step9.click()
    logger.info("결제 동의 2 클릭")
    time.sleep(2)
except NoSuchElementException as e:
    logger.error(f"결제 동의 2 체크박스를 찾을 수 없음: {str(e)}")
    raise

#결제 클릭
logger.info("최종 결제 버튼 클릭 준비")
handle_popups(driver)

# 결제 버튼이 클릭 가능할 때까지 대기
try:
    logger.info("결제 버튼 대기 중...")
    step10 = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//*[@id='container']/div/div[2]/div/div[3]/div[3]/div[5]/button"))
    )
    logger.info("결제 버튼 클릭")
    step10.click()
    logger.info("결제 요청 완료")
    time.sleep(2)
except TimeoutException as e:
    logger.error(f"결제 버튼을 찾을 수 없음: {str(e)}")
    raise



'''
# alert 등장 - 꼭 확인 클릭 필요
handle_popups(driver)
must_accept_alert(driver)  # 여기서 Alert 반드시 확인
time.sleep(2)
handle_popups(driver)

# /html/body/div[1]/div[3]/div/div[1]/div[2]/form/div/p/a[2]/span 클릭
handle_popups(driver)
step4 = driver.find_element(By.XPATH, "/html/body/div[1]/div[3]/div/div[1]/div[2]/form/div/p/a[2]/span")
step4.click()
time.sleep(2)
handle_popups(driver)

# /html/body/div[2]/div[3]/div/div[1]/div[2]/form/div[2]/div[2]/table/tbody/tr/td[3]/input 클릭
handle_popups(driver)
step5 = driver.find_element(By.XPATH, "/html/body/div[2]/div[3]/div/div[1]/div[2]/form/div[2]/div[2]/table/tbody/tr/td[3]/input")
step5.click()
time.sleep(2)
handle_popups(driver)

# 메인 코드에서 팝업 처리 부분 수정
# 현재 메인창 핸들 저장
main_handle = driver.current_window_handle

# /html/body/div[2]/div[3]/div/div[1]/div[2]/p/a[1]/span 클릭 -> 팝업 등장
handle_popups(driver)
step6 = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/div[3]/div/div[1]/div[2]/p/a[1]/span"))
)
step6.click()
handle_popups(driver)


time.sleep(2)  # 팝업이 새 창으로 뜰 시간을 잠시 대기

# 팝업 창에서 수행할 동작 정의
def popup_actions(popup_driver):
    # 팝업 창 안에서 요소를 찾아 클릭
    popup_click = WebDriverWait(popup_driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "/html/body/div/div[2]/div[1]/div[2]/a/p"))
    )
    popup_click.click()
    time.sleep(2)

    # 비밀번호 입력 필드 찾아서 입력
    step7 = WebDriverWait(popup_driver, 10).until(
        EC.presence_of_element_located((By.XPATH, "/html/body/div[1]/div[2]/div[1]/div/form/input[1]"))
    )
    step7.click()
    time.sleep(1)
    step7.send_keys(korail_pass_bank)
    time.sleep(1)

    # 최종 클릭
    
    final_click = WebDriverWait(popup_driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "/html/body/div[2]/a/p"))
    )
    final_click.click()
    time.sleep(3)

# 팝업 창 처리 실행
handle_popup_window(driver, main_handle, popup_actions)
# 마지막 단계: alert 처리 후 iframe으로 전환하여 버튼 클릭
try:
    # iframe이 로드될 때까지 대기
    iframe = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "mainframeSaleInfo"))
    )
    
    # iframe으로 전환
    driver.switch_to.frame(iframe)
    
    # iframe 내부의 버튼이 클릭 가능할 때까지 대기
    button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "/html/body/div/form/table/tbody/tr/td/p[1]/a[2]/span"))
    )
    
    # 버튼 클릭
    button.click()
    
    # 알림창이 나타날 때까지 대기 후 '확인' 클릭
    try:
        WebDriverWait(driver, 5).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert_text = alert.text
        print(f"알림창 메시지: {alert_text}")
        alert.accept()  # '확인' 버튼 클릭
        print("알림창 확인 버튼 클릭 완료")
    except TimeoutException:
        print("알림창이 나타나지 않았습니다.")
    
    # 기본 컨텐츠로 돌아가기
    driver.switch_to.default_content()

except TimeoutException:
    print("iframe 또는 버튼을 찾을 수 없습니다.")
    raise
except Exception as e:
    print(f"오류 발생: {str(e)}")
    
    # 예외 발생 시에도 알림창 처리 시도
    try:
        alert = driver.switch_to.alert
        alert.accept()
        print("예외 처리 중 알림창 확인 버튼 클릭 완료")
    except:
        pass
    
    raise
finally:
    time.sleep(3)

# 종료
logger.info("결제 프로세스 완료, 브라우저 종료")
time.sleep(3)
driver.quit()
logger.info("코레일 결제 스크립트 종료")
'''