"""
네이버 스마트스토어 리뷰 크롤러
- Selenium + XPath 기반
- 팝업 오픈 → 최신순 정렬 → 무한 스크롤 수집
- 결과: Google Sheets 첫 번째 시트에 이어서 추가
"""

import time
import re
import os
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import gspread
from google.oauth2.service_account import Credentials


# ─────────────────────────────────────────────
# ✅ 수집할 상품 URL
PRODUCT_URL = "https://brand.naver.com/minoxell/products/12538178823"

# ✅ 최대 수집 개수 (None = 전체 수집 / 테스트시 100 권장)
MAX_REVIEWS = 50

# ✅ 스크롤 대기 시간 (초) - 느린 환경이면 2~3으로 늘리세요
SCROLL_WAIT = 1.5
# ─────────────────────────────────────────────

# XPath 상수
XPATH = {
    "review_popup_btn": '//*[@id="REVIEW"]/div/div/div[2]/button',
    "sort_latest":      '//*[@id="REVIEW_LIST_TOP"]/div[2]/div/div[2]/div/ul[2]/li[2]/button',
    "review_items":     '//*[starts-with(@id, "REVIEW_ITEM_")]',
    "content":          './div[1]/div[1]/div[2]/div[2]/a',
    "star":             './div[1]/div[1]/div[2]/div[1]',
    "date":             './div[1]/div[1]/div[2]/div[2]/span[2]',
    "author":           './div[1]/div[1]/div[2]/div[2]/span[1]',
    "option":           './/button/span[contains(@id, "review_option_") or parent::button[contains(@id, "review_option_")]]',
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_gsheet():
    """Google Sheets 첫 번째 시트 반환"""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    spreadsheet_id = os.environ.get("SPREADSHEET_ID")

    if not creds_json or not spreadsheet_id:
        raise ValueError(
            "환경변수 GOOGLE_CREDENTIALS 또는 SPREADSHEET_ID가 설정되지 않았습니다.\n"
            "GitHub Secrets에 등록되어 있는지 확인해주세요."
        )

    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(spreadsheet_id)
    sheet = spreadsheet.get_worksheet(0)  # 첫 번째 시트 자동 선택
    print(f"📊 연결된 시트: '{sheet.title}'")
    return sheet


def ensure_header(sheet):
    """헤더가 없으면 첫 행에 추가"""
    headers = ["번호", "별점", "리뷰내용", "작성일", "옵션", "작성자", "수집일시"]
    first_row = sheet.row_values(1)
    if first_row != headers:
        sheet.insert_row(headers, 1)
        print("📋 헤더 추가 완료")


def get_next_row_and_num(sheet):
    """다음 빈 행 번호와 리뷰 순번 반환"""
    all_values = sheet.get_all_values()
    next_row = len(all_values) + 1
    # 헤더 제외한 데이터 행 수 = 현재까지 수집된 리뷰 수
    review_count = max(0, len(all_values) - 1)
    return next_row, review_count


def setup_driver() -> webdriver.Chrome:
    """크롬 드라이버 설정"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def click_element(driver, xpath: str, timeout: int = 10, description: str = ""):
    """XPath로 요소 찾아서 클릭"""
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.3)
        el.click()
        if description:
            print(f"  ✅ {description} 클릭 완료")
        return True
    except Exception as e:
        if description:
            print(f"  ❌ {description} 클릭 실패: {e}")
        return False


def open_review_popup(driver) -> bool:
    """리뷰 전체보기 팝업 열기 → 최신순 정렬"""
    print("📋 리뷰 팝업 열기...")
    if not click_element(driver, XPATH["review_popup_btn"], XPATH["review_popup_btn"], description="리뷰 전체보기"):
        return False
    time.sleep(2)

    print("🔃 최신순 정렬 중...")
    if not click_element(driver, XPATH["sort_latest"], description="최신순 정렬"):
        return False
    time.sleep(2)
    return True


def get_text_safe(el, xpath: str) -> str:
    """하위 요소 텍스트 안전하게 추출"""
    try:
        found = el.find_elements(By.XPATH, xpath)
        if found:
            return found[0].text.strip()
    except Exception:
        pass
    return ""


def parse_star(star_text: str) -> str:
    """별점 텍스트에서 숫자 추출"""
    match = re.search(r"[\d.]+", star_text)
    return match.group() if match else star_text


def collect_reviews(driver) -> list[dict]:
    """무한 스크롤로 전체 리뷰 수집"""
    all_reviews = {}
    last_count = 0
    no_new_streak = 0

    print("\n🚀 리뷰 수집 시작 (무한 스크롤)\n")

    while True:
        items = driver.find_elements(By.XPATH, XPATH["review_items"])

        for item in items:
            try:
                item_id = item.get_attribute("id")
                if item_id in all_reviews:
                    continue

                content = get_text_safe(item, XPATH["content"])
                star    = parse_star(get_text_safe(item, XPATH["star"]))
                date    = get_text_safe(item, XPATH["date"])
                author  = get_text_safe(item, XPATH["author"])
                option  = get_text_safe(item, XPATH["option"])

                if content:
                    all_reviews[item_id] = {
                        "별점":   star,
                        "리뷰내용": content,
                        "작성일":  date,
                        "옵션":   option,
                        "작성자":  author,
                    }
            except Exception:
                continue

        current_count = len(all_reviews)
        print(f"  📜 현재까지 수집: {current_count}개", end="\r")

        if MAX_REVIEWS and current_count >= MAX_REVIEWS:
            print(f"\n  ⛔ 최대 수집 개수({MAX_REVIEWS}개) 도달")
            break

        if current_count == last_count:
            no_new_streak += 1
            if no_new_streak >= 3:
                print(f"\n  ⛔ 더 이상 새 리뷰 없음 → 수집 종료")
                break
        else:
            no_new_streak = 0

        last_count = current_count
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(SCROLL_WAIT)

    return list(all_reviews.values())


def save_to_sheet(sheet, reviews: list[dict]):
    """리뷰 데이터를 구글 시트에 이어서 추가"""
    ensure_header(sheet)
    next_row, review_count = get_next_row_and_num(sheet)
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for i, r in enumerate(reviews, 1):
        rows.append([
            review_count + i,
            r.get("별점", ""),
            r.get("리뷰내용", ""),
            r.get("작성일", ""),
            r.get("옵션", ""),
            r.get("작성자", ""),
            collected_at,
        ])

    # 한 번에 업로드 (API 호출 최소화)
    sheet.append_rows(rows, value_input_option="USER_ENTERED")
    print(f"📊 구글 시트 '{sheet.title}'에 {len(rows)}개 추가 완료 (총 {review_count + len(rows)}개)")


def main():
    print("=" * 50)
    print("  네이버 스마트스토어 리뷰 크롤러")
    print("=" * 50)

    if "YOUR_STORE" in PRODUCT_URL:
        print("\n❌ PRODUCT_URL을 실제 상품 URL로 변경해주세요!")
        return

    # 구글 시트 연결
    print("\n🔑 Google Sheets 연결 중...")
    sheet = get_gsheet()

    # 크롤링
    driver = setup_driver()
    try:
        print(f"\n🔗 접속 중: {PRODUCT_URL}")
        driver.get(PRODUCT_URL)
        time.sleep(6)

        if not open_review_popup(driver):
            print("❌ 팝업 열기 실패 → 종료")
            return

        reviews = collect_reviews(driver)
    finally:
        driver.quit()

    # 저장
    if reviews:
        save_to_sheet(sheet, reviews)
        print(f"\n✅ 완료! 총 {len(reviews)}개 리뷰 수집 → 구글 시트 저장 완료")
    else:
        print("\n⚠️ 수집된 리뷰가 없습니다. URL과 XPath를 확인해주세요.")


if __name__ == "__main__":
    main()
