import asyncio
import json
import aiohttp
import time
import os
import logging
import re
from prometheus_client import start_http_server, Gauge

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
IS_PROXY_UP = Gauge("is_proxy_up", "Health status of proxy", ['proxy_ip'])
PROXY_LATENCY = Gauge("proxy_latency_ms", "Latency of proxy", ['proxy_ip'])

JSON_PATH = os.getenv("JSON_PATH", "proxys.json")
TEST_URL = os.getenv("TEST_URL", "http://httpbin.org/ip")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 10))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 5))
PROMETHEUS_SERVER_PORT = int(os.getenv("PROMETHEUS_SERVER_PORT", 8888))
RE =  r'^http://([^:]+):([^@]+)@(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})$'



def get_proxies():
    proxies = []
    total_proxies_count = 0
    if not os.path.exists(JSON_PATH):
        logger.error("Cannot find JSON file! Path: %s", JSON_PATH)
        return proxies

    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        servers = data["servers"]
        for server in servers:
            total_proxies_count += 1
            if not server.get("in_use"):
                continue
            proxy_url = server["url"]
            if not re.match(RE, proxy_url):
                logger.error("Invalid proxy url: %s", proxy_url)
                continue
            proxies.append(proxy_url)
    except Exception as e:
        logger.error("Error while getting proxies: %s", e)
    return proxies


async def check_proxy(proxy_url):
    match = re.match(RE, proxy_url)
    proxy_ip = f"{match.group(3)}:{match.group(4)}" if match else "unknown_ip"
    try:
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            async with session.get(TEST_URL, proxy=proxy_url, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status == 200:
                    IS_PROXY_UP.labels(proxy_ip).set(1)
                    PROXY_LATENCY.labels(proxy_ip).set((time.time() - start_time) * 1000)
                    logger.info(f"Proxy {proxy_url} up.")
                else:
                    IS_PROXY_UP.labels(proxy_ip).set(0)
                    PROXY_LATENCY.labels(proxy_ip).set(5000)
                    logger.warning(f"Proxy {proxy_url} is down.")
    except Exception as e:
        IS_PROXY_UP.labels(proxy_ip).set(0)
        PROXY_LATENCY.labels(proxy_ip).set(5000)
        logger.warning(f"Proxy {proxy_url} is down with error: {e}")


async def check_loop():
    while True:
        proxies = get_proxies()
        if proxies:
            tasks = [check_proxy(proxy_url) for proxy_url in proxies]
            await asyncio.gather(*tasks)
        else:
            logger.warning("No active proxies to test.")

        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    start_http_server(PROMETHEUS_SERVER_PORT)
    logger.info(f"Prometheus server started on port {PROMETHEUS_SERVER_PORT}")

    try:
        asyncio.run(check_loop())
    except KeyboardInterrupt:
        logger.info(f"Closing server.")
