"""SSH client for communicating with sshsign for offer logging and document signing."""

from __future__ import annotations

import json
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def _run_ssh(host: str, args: list[str], stdin_data: str | None = None) -> dict:
    """Run an SSH command against sshsign and return parsed JSON output.

    Joins all args into a single shell-quoted remote command to prevent
    SSH from splitting arguments containing spaces.
    """
    import shlex
    remote_cmd = " ".join(shlex.quote(a) for a in args)
    cmd = ["ssh", host, remote_cmd]
    logger.debug("Running: ssh %s %s", host, remote_cmd)

    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        logger.error("sshsign error: %s", result.stderr)
        raise RuntimeError(f"sshsign command failed: {result.stderr.strip()}")

    return json.loads(result.stdout)


def log_offer(
    host: str,
    negotiation_id: str,
    round_num: int,
    from_party: str,
    offer_type: str,
    metadata: dict,
    previous_tx: int | None = None,
) -> dict:
    """Log a negotiation offer to sshsign/immudb."""
    args = [
        "log-offer",
        "--negotiation-id", negotiation_id,
        "--round", str(round_num),
        "--from", from_party,
        "--type", offer_type,
        "--metadata", json.dumps(metadata),
        "--previous-tx", str(previous_tx or 0),
    ]
    return _run_ssh(host, args)


def sign_document(
    host: str,
    key_id: str,
    doc_type: str,
    payload: str,
    metadata: dict,
    session_id: str | None = None,
) -> dict:
    """Submit a document hash for signing."""
    args = [
        "sign",
        "--type", doc_type,
        "--key-id", key_id,
        "--metadata", json.dumps(metadata),
    ]
    if session_id:
        args.extend(["--session-id", session_id])
    return _run_ssh(host, args, stdin_data=payload)


def get_history(host: str, negotiation_id: str) -> dict:
    """Retrieve the full negotiation history from sshsign/immudb."""
    args = ["history", "--negotiation-id", negotiation_id]
    return _run_ssh(host, args)


def create_signing_key(
    host: str,
    scope: str,
    tier: str,
    constraints: dict,
    require_signature: bool = True,
) -> dict:
    """Create a signing key on sshsign with constraints."""
    args = [
        "create-key",
        "--scope", scope,
        "--tier", tier,
        "--constraints", json.dumps(constraints),
    ]
    if require_signature:
        args.append("--require-signature")
    return _run_ssh(host, args)


def get_envelope(host: str, pending_id: str) -> dict:
    """Retrieve the evidence envelope for a pending signature.

    Returns the full envelope (including signature_image) when approved,
    or status: pending when still waiting.
    """
    args = ["get-envelope", "--id", pending_id]
    return _run_ssh(host, args)


def poll_for_new_offer(
    host: str,
    negotiation_id: str,
    expected_count: int,
    interval: int = 2,
    timeout: int = 300,
) -> list[dict]:
    """Poll history until a new offer appears.

    Waits until the history has more entries than expected_count.
    Returns the full history list.
    Raises TimeoutError if no new offer within timeout seconds.
    """
    elapsed = 0
    while elapsed < timeout:
        try:
            history = get_history(host, negotiation_id)
            if isinstance(history, list) and len(history) > expected_count:
                return history
        except Exception:
            pass
        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(
        f"No new offer in {negotiation_id} within {timeout}s"
    )


def poll_for_approval(
    host: str,
    pending_id: str,
    interval: int = 5,
    timeout: int = 300,
) -> dict:
    """Poll get-envelope until the pending signature is approved.

    Returns the full envelope response on approval.
    Raises TimeoutError if not approved within timeout seconds.
    """
    elapsed = 0
    while elapsed < timeout:
        result = get_envelope(host, pending_id)
        if result.get("status") == "approved":
            return result
        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(
        f"Pending signature {pending_id} not approved within {timeout}s"
    )
