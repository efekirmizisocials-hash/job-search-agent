"""Conservative ATS routing based on parsed hostnames, never URL substrings."""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import ipaddress

OPEN_ATS = {
    "greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io"),
    "lever": ("jobs.lever.co", "jobs.eu.lever.co"),
    "ashby": ("jobs.ashbyhq.com",),
    "teamtailor": ("teamtailor.com",),
    "recruitee": ("recruitee.com",),
    "smartrecruiters": ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"),
}
MANUAL_ATS = {"workday": ("myworkdayjobs.com", "myworkdaysite.com"),
              "linkedin": ("linkedin.com",), "taleo": ("taleo.net",),
              "successfactors": ("successfactors.com", "successfactors.eu")}


def public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def detect_ats(url: str) -> str:
    if not public_url(url):
        return "manual"
    host = urlsplit(url).hostname.lower().rstrip(".")
    for name, domains in {**OPEN_ATS, **MANUAL_ATS}.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return "manual"


def is_open_ats(url: str) -> bool:
    return detect_ats(url) in OPEN_ATS


def canonical_url(url: str) -> str:
    """Keep requisition parameters; remove known attribution parameters only."""
    try:
        p = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref", "referral"}]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), urlencode(sorted(query)), ""))
    except ValueError:
        return url
