from urllib.parse import urlparse, urlunparse

MAX_URL_LENGTH = 2048

BLOCKED_DOMAINS = {
    "evil.com",
    "malware.example.com",
    "phishing.example.com",
}


def is_blocked_domain(hostname: str | None) -> bool:
    if hostname is None:
        return True
    return hostname.lower() in BLOCKED_DOMAINS


def validate_url(url: str) -> str:
    """Format check, normalization, and blocklist validation."""

    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds maximum length of {MAX_URL_LENGTH} characters.")
    
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must have an http or https scheme.")
    if is_blocked_domain(parsed.hostname):
        raise ValueError("URL contains a blocked domain.")
    
    # Normalize the URL
    scheme = "https" # force https for normalization
    netloc = parsed.hostname.lower()
    if parsed.port:                                                                                                                                                    
        netloc += f":{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))

