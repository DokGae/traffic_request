import configparser
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import time
from datetime import datetime
from pathlib import Path
import requests

def load_settings():
    """setting.ini에서 실행 설정을 읽습니다."""
    settings_path = Path(__file__).with_name("setting.ini")
    config = configparser.ConfigParser()
    if not settings_path.is_file():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {settings_path}")
    config.read(settings_path, encoding="utf-8")
    try:
        section = config["settings"]
        return (
            section["url"],
            section.getint("total_requests"),
            section.getint("max_workers"),
            section.getint("timeout"),
        )
    except (KeyError, ValueError) as error:
        raise ValueError(
            "setting.ini의 [settings]에 url, total_requests, "
            "max_workers, timeout을 올바르게 설정하세요."
        ) from error


def save_settings(url, total_requests, max_workers, timeout):
    """실행 설정을 setting.ini에 저장합니다."""
    config = configparser.ConfigParser()
    config["settings"] = {
        "url": url,
        "total_requests": str(total_requests),
        "max_workers": str(max_workers),
        "timeout": str(timeout),
    }
    settings_path = Path(__file__).with_name("setting.ini")
    with settings_path.open("w", encoding="utf-8") as settings_file:
        config.write(settings_file)


def read_positive_int(prompt, current):
    """숫자 설정을 입력받고, 빈 입력이면 기존 값을 유지합니다."""
    while True:
        value = input(f"{prompt} [{current}]: ").strip()
        if not value:
            return current
        try:
            number = int(value)
            if number < 1:
                raise ValueError
            return number
        except ValueError:
            print("1 이상의 정수를 입력하세요.")


def settings_menu():
    """설정값을 입력받아 저장합니다."""
    try:
        url, total_requests, max_workers, timeout = load_settings()
    except (FileNotFoundError, ValueError) as error:
        print(error)
        url, total_requests, max_workers, timeout = (
            "https://www.yugiyu5.com/mall/48", 5000, 5, 20
        )

    print("\n[설정 메뉴] (Enter를 누르면 현재 값을 유지합니다.)")
    new_url = input(f"2-1 사이트 주소 [{url}]: ").strip() or url
    new_total_requests = read_positive_int("2-2 총 요청 수", total_requests)
    new_max_workers = read_positive_int("2-3 동시 실행 수", max_workers)
    new_timeout = read_positive_int("2-4 요청 타임아웃(초)", timeout)

    save_settings(
        new_url, new_total_requests, new_max_workers, new_timeout
    )
    print("설정을 저장했습니다.\n")


def menu():
    """프로그램 시작 메뉴입니다."""
    while True:
        print("[메뉴]")
        print("1. 시작")
        print("2. 설정")
        print("0. 종료")
        choice = input("선택: ").strip()

        if choice == "1":
            print("\n[시작 메뉴]")
            print("1-1. 무한 반복")
            print("1-2. 설정된 요청 횟수만큼 실행")
            print("0. 돌아가기")
            start_choice = input("선택: ").strip()
            if start_choice == "1-1":
                run(infinite=True)
            elif start_choice == "1-2":
                run(infinite=False)
            elif start_choice != "0":
                print("1-1, 1-2, 0 중에서 선택하세요.\n")
        elif choice == "2":
            settings_menu()
        elif choice == "0":
            print("종료합니다.")
            return
        else:
            print("1, 2, 0 중에서 선택하세요.\n")


def check_once(request_id, url, timeout):
    # 요청마다 독립적인 세션 사용: 쿠키를 서로 공유하지 않음
    with requests.Session() as session:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()

        match = re.search(
            r'<span[^>]*>\s*조회\s*</span>\s*<strong[^>]*>(.*?)</strong>',
            response.text,
            re.S,
        )
        if not match:
            raise ValueError("조회수 영역을 찾지 못했습니다.")

        text = re.sub(r"<[^>]+>", "", match.group(1))
        count = re.search(r"([\d,]+)\s*회", text)

        if not count:
            raise ValueError("조회수 숫자를 찾지 못했습니다.")

        return request_id, int(count.group(1).replace(",", ""))


def run(infinite=False):
    url, total_requests, max_workers, timeout = load_settings()
    if total_requests < 1 or max_workers < 1 or timeout < 1:
        raise ValueError("요청 수와 동시 실행 수는 1 이상이어야 합니다.")

    target_requests = None if infinite else total_requests

    started_at = datetime.now().astimezone()
    started_timer = time.perf_counter()

    def log(message):
        now = datetime.now().astimezone()
        elapsed = time.perf_counter() - started_timer
        print(
            f"[{now:%Y-%m-%d %H:%M:%S%z}] "
            f"[경과 {elapsed:.1f}초] {message}",
            flush=True,
        )

    log(
        f"시작 | 총 {'무한' if infinite else total_requests}회 | "
        f"최대 동시 실행 {max_workers}개"
    )

    successes = 0
    failures = 0

    executor = ThreadPoolExecutor(max_workers=max_workers)
    futures = {}
    next_request_id = 1
    completed = 0

    def submit_next():
        nonlocal next_request_id
        if target_requests is not None and next_request_id > target_requests:
            return False
        futures[executor.submit(
            check_once, next_request_id, url, timeout
        )] = next_request_id
        next_request_id += 1
        return True

    try:
        for _ in range(max_workers):
            if not submit_next():
                break

        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                request_id = futures.pop(future)
                completed += 1

                try:
                    _, count = future.result()
                    successes += 1
                    log(
                        f"[{completed}/{'∞' if infinite else total_requests}] "
                        f"요청 #{request_id}: {count:,}회"
                    )
                except (requests.RequestException, ValueError) as error:
                    failures += 1
                    log(
                        f"[{completed}/{'∞' if infinite else total_requests}] "
                        f"요청 #{request_id}: 실패 — {error}"
                    )
                submit_next()
    except KeyboardInterrupt:
        print("\n중지 요청을 받았습니다. 대기 중인 요청을 취소합니다.")
        for future in futures:
            future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)
        print("프로그램을 종료합니다.")
        return
    else:
        executor.shutdown(wait=True)

    log(f"완료 | 성공 {successes}건 | 실패 {failures}건")
    print(f"시작 시각: {started_at:%Y-%m-%d %H:%M:%S%z}")
    print(f"총 소요 시간: {time.perf_counter() - started_timer:.1f}초")

if __name__ == "__main__":
    menu()
