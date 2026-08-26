from urllib.error import URLError
from urllib.request import urlopen


def url_health(url: str) -> bool:
    try:
        with urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except (OSError, URLError):
        return False


def docling_health(base_url: str) -> bool:
    return url_health(f"{base_url}/health")
