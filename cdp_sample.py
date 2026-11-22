from playwright.sync_api import sync_playwright, expect

pageLink = "https://www.youtube.com/"

def work(page):
    page.pause()

def work_daum(page):
    #pageLink = "https://top.cafe.daum.net/"

	# 1. 다이얼로그가 뜰 때 '확인(accept)'을 누르도록 이벤트 리스너 등록
    page.on("dialog", lambda dialog: dialog.accept())
    # 전체 link 로케이터 정의
    links = page.get_by_role("link")
  
    count = 1  # 전체 번호 (1부터 30까지 증가)

    for page_num in range(3):  # 총 3페이지 반복
        links = page.get_by_role("link")

        # 각 페이지에서 10개씩 추출 (22번 ~ 31번 인덱스 = 총 10개)
        # 만약 22~33번(12개)을 원하시면 range(22, 34)로 변경하세요.
        for i in range(22, 32):
            target = links.nth(i)

            text = " ".join(target.inner_text().split())
            href = target.get_attribute("href")

            print(f"{count}.[제목: {text}]({href})\n")
            count += 1

        # 마지막 3번째 페이지에서는 '다음 인기글' 버튼을 누르지 않음
        if page_num < 2:
            # Playwright get_by_role 올바른 문법 적용
            page.get_by_role("button", name="다음 인기글").click()
            # 다음 페이지 목록이 바뀔 때까지 잠시 대기 (필요에 따라 시간 조절)
            page.wait_for_timeout(1000)
  
    page.pause()


with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(pageLink)
    work(page)    

# 다음 실베 30개 긁어오기
#    work_daum(page)

#    except KeyboardInterrupt:
#        print("\n사용자에 의해 반복 작업이 중단되었습니다.")
#    finally:
#        browser.close()
