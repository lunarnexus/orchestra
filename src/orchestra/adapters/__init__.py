"""Host adapter helpers."""

from orchestra.adapters.hermes import normalize_hermes_session_id
from orchestra.adapters.pi import normalize_pi_session_id

__all__ = ["normalize_hermes_session_id", "normalize_pi_session_id"]
