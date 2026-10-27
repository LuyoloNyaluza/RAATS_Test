
import csv
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path

BASE_URL = "http://localhost:8000"
ENDPOINT = "/health"
TOTAL_REQUESTS = 50
CONCURRENT_WORKERS = 5
TIMEOUT_SECONDS = 10

OUTPUT_DIR = Path("data") / "load_tests"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = OUTPUT_DIR / f"load_test_{timestamp}.csv"


def send_request(request_number):
    url = BASE_URL + ENDPOINT
    request = Request(url, method="GET")
    start = time.perf_counter()
    status_code = ""
    error = ""
    response_body = ""

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status_code = response.status
            response_body = response.read().decode(
                "utf-8", errors="replace"
            )

    except HTTPError as exc:
        status_code = exc.code
        error = f"HTTPError: {exc}"

    except (URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = (time.perf_counter() - start) * 1000
    success = (
        status_code == 200
        and '"status"' in response_body
        and '"healthy"' in response_body
    )

    return {
        "request_number": request_number,
        "timestamp": datetime.now().astimezone().isoformat(),
        "endpoint": url,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "success": success,
        "error": error,
    }


def main():
    print("RAATS API Load Test")
    print(f"Endpoint: {BASE_URL + ENDPOINT}")
    print(f"Requests: {TOTAL_REQUESTS}")
    print(f"Concurrent workers: {CONCURRENT_WORKERS}")
    print("Starting in 3 seconds. Monitor docker stats in another terminal.")
    time.sleep(3)

    results = []
    start_time = time.perf_counter()

    with ThreadPoolExecutor(
        max_workers=CONCURRENT_WORKERS
    ) as executor:
        futures = [
            executor.submit(send_request, number)
            for number in range(1, TOTAL_REQUESTS + 1)
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)

            print(
                f"Request {result['request_number']:02d}: "
                f"HTTP {result['status_code'] or 'ERROR'} | "
                f"{result['latency_ms']:.2f} ms | "
                f"{'PASS' if result['success'] else 'FAIL'}"
            )

    duration = time.perf_counter() - start_time
    results.sort(key=lambda row: row["request_number"])

    with OUTPUT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "request_number",
                "timestamp",
                "endpoint",
                "status_code",
                "latency_ms",
                "success",
                "error",
            ],
        )
        writer.writeheader()
        writer.writerows(results)

    latencies = sorted(row["latency_ms"] for row in results)
    successes = sum(row["success"] for row in results)
    failures = TOTAL_REQUESTS - successes
    p95_index = max(0, math.ceil(0.95 * len(latencies)) - 1)

    print("\n--- LOAD TEST SUMMARY ---")
    print(f"Total requests: {TOTAL_REQUESTS}")
    print(f"Successful health checks: {successes}")
    print(f"Failed requests/checks: {failures}")
    print(f"Success rate: {successes / TOTAL_REQUESTS * 100:.2f}%")
    print(f"Total duration: {duration:.2f} seconds")
    print(f"Throughput: {TOTAL_REQUESTS / duration:.2f} requests/second")
    print(f"Average latency: {sum(latencies) / len(latencies):.2f} ms")
    print(f"P95 latency: {latencies[p95_index]:.2f} ms")
    print(f"Maximum latency: {max(latencies):.2f} ms")
    print(f"CSV results: {OUTPUT_FILE.resolve()}")


if __name__ == "__main__":
    main()
