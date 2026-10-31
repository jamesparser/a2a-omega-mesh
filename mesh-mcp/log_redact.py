"""Redaction helper so never log secrets; pass explicit fields only."""
import hashlib
import re


def log_redact(obj):
    """Redact credential-looking strings before any log line is emitted.

    Long opaque token-shaped strings are reduced to length + 8 hex chars of
    their sha256 (enables equality comparisons in logs without revealing the
    value). Non-string values pass through unchanged.
    """
    if isinstance(obj, dict):
        return {k: log_redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [log_redact(x) for x in obj]
    if isinstance(obj, str) and len(obj) >= 24 and re.fullmatch(r'[A-Za-z0-9_+/=-]+', obj):
        return '<redacted:%d:%s>' % (len(obj), hashlib.sha256(obj.encode()).hexdigest()[:8])
    return obj
