from playwright.sync_api import sync_playwright
from datetime import datetime
from urllib.parse import urljoin

pageLink = "https://www.youtube.com/@umarjamilai/videos"


def work(page):

    # 1. 영상 URL과 제목 수집
    videos = page.locator("#contents a").evaluate_all(
        """elements => elements.map(el => ({
            url: el.getAttribute('href'),
            title: el.getAttribute('title') || el.innerText.trim()
        }))
        .filter(video => video.url)
        """
    )

    # 2. 중복 URL 제거
    unique_videos = {}
    for video in videos:
        unique_videos[video["url"]] = video

    videos = list(unique_videos.values())

    print(f"중복 제거 후 영상 개수: {len(videos)}")

    # 3. 날짜 범위 직접 입력
    start_date = input("시작 날짜 입력 (YYYY-MM-DD): ")
    end_date = input("종료 날짜 입력 (YYYY-MM-DD): ")

    start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

    if start_date > end_date:
        print("시작 날짜가 종료 날짜보다 늦습니다.")
        return

    # 4. 각 영상 페이지에서 업로드 날짜 수집
    results = []

    for index, video in enumerate(videos, start=1):

        video_url = urljoin("https://www.youtube.com", video["url"])

        print(f"[{index}/{len(videos)}] 수집 중: {video['title']}")

        try:
            page.goto(video_url, wait_until="domcontentloaded")

            # 영상의 실제 업로드 날짜
            date_text = page.locator(
                "meta[itemprop='datePublished']"
            ).get_attribute("content", timeout=10000)

            upload_date = datetime.strptime(
                date_text[:10], "%Y-%m-%d"
            ).date()

            # 5. 입력한 날짜 범위에 해당하는 영상만 저장
            if start_date <= upload_date <= end_date:

                results.append({
                    "date": str(upload_date),
                    "title": video["title"],
                    "url": video_url
                })

        except Exception as e:
            print(f"수집 실패: {video_url}")
            print(e)

    # 6. 날짜순 정렬
    results.sort(key=lambda x: x["date"], reverse=True)

    # 7. 결과 출력
    print("\n========== 검색 결과 ==========")

    for video in results:
        print(f"날짜: {video['date']}")
        print(f"제목: {video['title']}")
        print(f"URL: {video['url']}")
        print("-------------------------------")

    print(f"검색된 영상: {len(results)}개")

    page.pause()


with sync_playwright() as p:

    browser = p.chromium.connect_over_cdp("http://localhost:9222")

    context = browser.contexts[0]

    page = context.pages[0] if context.pages else context.new_page()

    page.goto(pageLink)

    work(page)