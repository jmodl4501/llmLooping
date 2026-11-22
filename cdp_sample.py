from playwright.sync_api import sync_playwright, expect

pageLink = "https://blog.naver.com/"


def work(page):
	# 1. 다이얼로그가 뜰 때 '확인(accept)'을 누르도록 이벤트 리스너 등록
    page.on("dialog", lambda dialog: dialog.accept())
    page.pause()


with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(pageLink)
    work(page)

#    except KeyboardInterrupt:
#        print("\n사용자에 의해 반복 작업이 중단되었습니다.")
#    finally:
#        browser.close()
