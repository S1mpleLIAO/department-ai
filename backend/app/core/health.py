from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def url_health(url: str, accepted_errors: tuple[int, ...] = ()) -> bool:
    try:
        with urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except HTTPError as error:
        return error.code in accepted_errors
    except (OSError, URLError):
        return False


def docling_health(base_url: str) -> bool:
    return url_health(f"{base_url}/health")


def harness_health(url: str) -> bool:
    return url_health(url, (401,))
