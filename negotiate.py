"""
APOA Negotiate -- bilateral agent-to-agent contract negotiation.

All configuration via .env file. Two modes:
  1. Local mode: both agents in one process (ROLE= blank)
  2. Distributed mode: each party runs their own agent (ROLE=founder or investor)

"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import webbrowser
from datetime import datetime, timezone

import os
import uuid as uuid_mod

from dotenv import load_dotenv
load_dotenv()
from pathlib import Path

from agents.claude_agent import ClaudeAgent
from agents.config import build_founder_constraints, build_investor_constraints
from documents.generator import generate_document, generate_executed_document
from protocol import (
    NegotiationState,
    ProtocolSchema,
    validate_apoa_constraints,
    validate_offer_structure,
    validate_offer_turn,
)
from sshsign_client import (
    get_history,
    log_offer,
    poll_for_approval,
    poll_for_new_offer,
    sign_document,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
MAX_VALIDATION_RETRIES = 3

# ANSI color codes
TEAL = "\033[38;5;37m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    return int(v) if v else default

def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    return float(v) if v else default

def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    return v.lower() in ("true", "1", "yes") if v else default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="APOA Negotiate: bilateral agent-to-agent contract negotiation",
    )
    # Schema
    parser.add_argument("--schema", default="schemas/safe.json")

    # Role (from .env or CLI)
    parser.add_argument("--role", default=_env("ROLE"), choices=["", "founder", "investor"])

    # APOA token paths
    parser.add_argument("--founder-token", default="")
    parser.add_argument("--investor-token", default="")
    parser.add_argument("--founder-pubkey", default="")
    parser.add_argument("--investor-pubkey", default="")

    # Constraints (from .env or CLI)
    parser.add_argument("--founder-cap-min", type=int, default=_env_int("FOUNDER_CAP_MIN", 8_000_000))
    parser.add_argument("--founder-cap-max", type=int, default=_env_int("FOUNDER_CAP_MAX", 12_000_000))
    parser.add_argument("--founder-discount-min", type=float, default=_env_float("FOUNDER_DISCOUNT_MIN", 0.20))
    parser.add_argument("--founder-discount-max", type=float, default=_env_float("FOUNDER_DISCOUNT_MAX", 0.25))
    parser.add_argument("--founder-pro-rata-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("FOUNDER_PRO_RATA_REQUIRED", True))
    parser.add_argument("--founder-mfn-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("FOUNDER_MFN_REQUIRED", False))
    parser.add_argument("--investor-cap-min", type=int, default=_env_int("INVESTOR_CAP_MIN", 6_000_000))
    parser.add_argument("--investor-cap-max", type=int, default=_env_int("INVESTOR_CAP_MAX", 10_000_000))
    parser.add_argument("--investor-discount-min", type=float, default=_env_float("INVESTOR_DISCOUNT_MIN", 0.15))
    parser.add_argument("--investor-discount-max", type=float, default=_env_float("INVESTOR_DISCOUNT_MAX", 0.25))
    parser.add_argument("--investor-pro-rata-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("INVESTOR_PRO_RATA_REQUIRED", False))
    parser.add_argument("--investor-mfn-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("INVESTOR_MFN_REQUIRED", False))

    # Party info (from .env or CLI)
    parser.add_argument("--sshsign-host", default=_env("SSHSIGN_HOST", "sshsign.dev"))
    parser.add_argument("--signing-key-id", default="")
    parser.add_argument("--negotiation-id", default=_env("NEGOTIATION_ID"))
    parser.add_argument("--session-id", default="")
    parser.add_argument("--founder-signing-key-id", default=_env("FOUNDER_SIGNING_KEY_ID"))
    parser.add_argument("--investor-signing-key-id", default=_env("INVESTOR_SIGNING_KEY_ID"))
    parser.add_argument("--investment-amount", type=float, default=_env_float("INVESTMENT_AMOUNT", 500_000.0))
    parser.add_argument("--company-name", default=_env("COMPANY_NAME", "Acme Corp"))
    parser.add_argument("--founder-name", default=_env("FOUNDER_NAME", "Jane Doe"))
    parser.add_argument("--founder-title", default=_env("FOUNDER_TITLE", "CEO"))
    parser.add_argument("--investor-name", default=_env("INVESTOR_NAME", "Angel Ventures"))
    parser.add_argument("--investor-firm", default=_env("INVESTOR_FIRM", ""))
    parser.add_argument("--date", default="")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--no-sshsign", action="store_true")
    parser.add_argument("--poll", action="store_true")
    parser.add_argument("--poll-timeout", type=int, default=0)
    parser.add_argument("--finalize", default="")
    parser.add_argument("--verbose", "-v", action="store_true")

    # Signature settings per party
    parser.add_argument("--founder-require-signature", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("FOUNDER_REQUIRE_SIGNATURE", True))
    parser.add_argument("--investor-require-signature", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=_env_bool("INVESTOR_REQUIRE_SIGNATURE", True))

    return parser.parse_args()



def load_apoa_token(token_path: str, pubkey_path: str) -> tuple:
    """Load and validate an APOA token, return (token, constraints_dict)."""
    from apoa import ValidationOptions, create_client
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    raw_jwt = Path(token_path).read_text().strip()

    public_key = None
    if pubkey_path:
        public_key = load_pem_public_key(Path(pubkey_path).read_bytes())

    client = create_client()
    result = client.validate_token(
        raw_jwt,
        ValidationOptions(public_key=public_key, clock_skew=60),
    )

    if not result.valid:
        raise ValueError(f"Invalid APOA token: {result.errors}")

    token = result.token
    service = next(
        (s for s in token.definition.services if s.service == "safe-agreement"),
        None,
    )
    if not service:
        raise ValueError("Token has no 'safe-agreement' service authorization")

    return token, service.constraints or {}


def spinner_print(message: str) -> None:
    print(f"  {TEAL}>{RESET} {message}", flush=True)


def display_offer(
    offer: dict,
    role: str,
    round_num: int,
    constraint_result: tuple,
    constraints: dict,
    previous_terms: dict | None = None,
) -> None:
    """Pretty-print an offer to the terminal with constraint proximity hints."""
    valid, violations = constraint_result

    role_color = TEAL if role == "founder" else YELLOW
    type_label = offer["type"].upper()

    print(f"\n{DIM}{'─'*60}{RESET}")
    print(f"  {BOLD}Round {round_num}{RESET}  {role_color}{role.upper()}{RESET}  {type_label}")
    print(f"{DIM}{'─'*60}{RESET}")

    if offer["type"] not in ("accept", "reject"):
        terms = offer.get("terms", {})
        cap = terms.get("valuation_cap", 0)
        discount = terms.get("discount_rate", 0)
        pro_rata = terms.get("pro_rata", False)
        mfn = terms.get("mfn", False)

        prev = previous_terms or {}

        cap_changed = prev and cap != prev.get("valuation_cap")
        cap_str = f"${cap:>12,.0f}"
        if cap_changed:
            cap_str = f"{TEAL}{cap_str}{RESET}"
        cap_hint = _constraint_hint("valuation_cap", cap, constraints)
        print(f"  Valuation Cap:  {cap_str}  {cap_hint}")

        disc_changed = prev and discount != prev.get("discount_rate")
        discount_str = f"{discount:>12.0%}"
        if disc_changed:
            discount_str = f"{TEAL}{discount_str}{RESET}"
        discount_hint = _constraint_hint("discount_rate", discount, constraints)
        print(f"  Discount Rate:  {discount_str}  {discount_hint}")

        pr_changed = prev and pro_rata != prev.get("pro_rata")
        pro_rata_str = f"{'Yes' if pro_rata else 'No':>12}"
        if pr_changed:
            pro_rata_str = f"{TEAL}{pro_rata_str}{RESET}"
        pro_rata_hint = _constraint_hint("pro_rata", pro_rata, constraints)
        print(f"  Pro-Rata:       {pro_rata_str}  {pro_rata_hint}")

        mfn_changed = prev and mfn != prev.get("mfn")
        mfn_str = f"{'Yes' if mfn else 'No':>12}"
        if mfn_changed:
            mfn_str = f"{TEAL}{mfn_str}{RESET}"
        print(f"  MFN:            {mfn_str}")

    if offer.get("message"):
        print(f"\n  {DIM}\"{offer['message']}\"{RESET}")

    if not valid:
        print(f"\n  {RED}APOA Violations:{RESET}")
        for v in violations:
            print(f"    {RED}- {v}{RESET}")

    print()


def _constraint_hint(field: str, value, constraints: dict) -> str:
    is_legacy = any(isinstance(v, dict) for v in constraints.values())

    if is_legacy:
        rules = constraints.get(field, {})
        if not rules:
            return ""
        min_val = rules.get("min")
        max_val = rules.get("max")
        required = rules.get("required")
    else:
        min_val = constraints.get(f"{field}_min")
        max_val = constraints.get(f"{field}_max")
        required = constraints.get(f"{field}_required")

    if required is not None and isinstance(value, bool):
        if required and not value:
            return f"{RED}(required){RESET}"
        if required and value:
            return f"{GREEN}(required){RESET}"
        return ""

    if min_val is not None and max_val is not None and isinstance(value, (int, float)):
        if value < min_val:
            return f"{RED}(below min {_fmt(field, min_val)}){RESET}"
        if value > max_val:
            return f"{RED}(above max {_fmt(field, max_val)}){RESET}"
        if value == min_val:
            return f"{YELLOW}(at floor){RESET}"
        if value == max_val:
            return f"{YELLOW}(at ceiling){RESET}"
        pct = (value - min_val) / (max_val - min_val) * 100
        return f"{DIM}({pct:.0f}% of range){RESET}"
    elif min_val is not None and isinstance(value, (int, float)):
        if value < min_val:
            return f"{RED}(below min {_fmt(field, min_val)}){RESET}"
        if value == min_val:
            return f"{YELLOW}(at floor){RESET}"
        return ""

    return ""


def _fmt(field: str, value) -> str:
    if "cap" in field and isinstance(value, (int, float)):
        return f"${value:,.0f}"
    if "rate" in field and isinstance(value, float):
        return f"{value:.0%}"
    return str(value)


def display_negotiation_summary(state: NegotiationState, elapsed_seconds: float) -> None:
    print(f"\n{TEAL}{'='*60}{RESET}")
    print(f"  {BOLD}Negotiation History{RESET}")
    print(f"{TEAL}{'='*60}{RESET}")

    print(f"  {'Round':<7} {'Party':<10} {'Type':<9} {'Cap':>12} {'Disc':>6} {'Pro-Rata':>9} {'TX':>6}")
    print(f"  {DIM}{'─'*59}{RESET}")

    for entry in state.history:
        round_num = entry.get("round", "?")
        party = entry.get("from", "?")
        offer_type = entry.get("type", "?")
        terms = entry.get("terms", {})
        tx = entry.get("immudb_tx", "")

        party_color = TEAL if party == "founder" else YELLOW

        if offer_type in ("accept", "reject"):
            print(f"  {round_num:<7} {party_color}{party:<10}{RESET} {BOLD}{offer_type:<9}{RESET} {'':>12} {'':>6} {'':>9} {DIM}{tx or ''}{RESET}")
        else:
            cap = f"${terms.get('valuation_cap', 0):,.0f}"
            disc = f"{terms.get('discount_rate', 0):.0%}"
            pr = "Yes" if terms.get("pro_rata") else "No"
            print(f"  {round_num:<7} {party_color}{party:<10}{RESET} {offer_type:<9} {cap:>12} {disc:>6} {pr:>9} {DIM}{tx or ''}{RESET}")

    print(f"  {DIM}{'─'*59}{RESET}")
    print(f"  {BOLD}{len(state.history)} offers{RESET} in {TEAL}{elapsed_seconds:.1f}s{RESET}")
    print()


def save_negotiation_log(
    state: NegotiationState,
    schema: ProtocolSchema,
    output_dir: Path,
    elapsed_seconds: float,
    using_tokens: bool,
) -> str:
    log_path = output_dir / f"{schema.negotiation_id}_log.json"
    log_data = {
        "negotiation_id": schema.negotiation_id,
        "protocol": schema.protocol,
        "version": schema.version,
        "document_type": schema.document_type,
        "outcome": state.outcome,
        "total_offers": len(state.history),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "authorization": "apoa_tokens" if using_tokens else "cli_args",
        "history": state.history,
    }
    if state.outcome == "accepted":
        log_data["agreed_terms"] = state.agreed_terms()

    log_path.write_text(json.dumps(log_data, indent=2, default=str))
    return str(log_path)


def build_constraints_from_args(args: argparse.Namespace) -> tuple[dict, dict]:
    founder_constraints = build_founder_constraints(
        cap_min=args.founder_cap_min,
        cap_max=args.founder_cap_max,
        discount_min=args.founder_discount_min,
        discount_max=args.founder_discount_max,
        pro_rata_required=args.founder_pro_rata_required,
        mfn_required=args.founder_mfn_required,
    )
    investor_constraints = build_investor_constraints(
        cap_min=args.investor_cap_min,
        cap_max=args.investor_cap_max,
        discount_min=args.investor_discount_min,
        discount_max=args.investor_discount_max,
        pro_rata_required=args.investor_pro_rata_required,
        mfn_required=args.investor_mfn_required,
    )
    return founder_constraints, investor_constraints


def print_header(schema: ProtocolSchema, state: NegotiationState, using_tokens: bool, role: str = "") -> None:
    print(f"\n{TEAL}{'='*60}{RESET}")
    print(f"  {BOLD}APOA Negotiate{RESET}")
    print(f"{TEAL}{'='*60}{RESET}")
    print(f"  Negotiation   {TEAL}{schema.negotiation_id}{RESET}")
    print(f"  Protocol      {schema.protocol} v{schema.version}")
    print(f"  Document      {schema.document_type}")
    print(f"  Max rounds    {state.max_rounds}")
    print(f"  First mover   {state.first_mover}")
    if role:
        role_color = TEAL if role == "founder" else YELLOW
        print(f"  Your role     {role_color}{role}{RESET}")
    if using_tokens:
        print(f"  Authorization {TEAL}APOA tokens (Ed25519){RESET}")
    print()


def _collect_all_signatures(
    args: argparse.Namespace,
    schema: ProtocolSchema,
    output_dir: Path,
    quiet: bool = False,
) -> list[dict]:
    """Collect signature envelopes from all parties in this negotiation."""
    from sshsign_client import get_envelope

    signers = []

    for role in ["founder", "investor"]:
        pending_file = output_dir / f"{schema.negotiation_id}_{role}_pending.txt"
        if not pending_file.exists():
            continue

        pending_id = pending_file.read_text().strip()
        if not pending_id:
            continue

        try:
            result = get_envelope(host=args.sshsign_host, pending_id=pending_id)
            if result.get("status") == "approved":
                envelope_data = result.get("envelope", {})
                signers.append({
                    "role": role,
                    "pending_id": pending_id,
                    "key_id": result.get("key_id", ""),
                    "signature": result.get("signature", ""),
                    "signature_image": envelope_data.get("signature_image"),
                    "audit_tx_id": result.get("audit_tx_id"),
                })
                if not quiet:
                    print(f"  {GREEN}{role}: signed{RESET}")
            else:
                if not quiet:
                    print(f"  {YELLOW}{role}: pending{RESET}")
        except Exception as e:
            logger.debug("Could not fetch envelope for %s: %s", role, e)
            if not quiet:
                print(f"  {DIM}{role}: unavailable{RESET}")

    return signers


def _poll_and_finalize(
    args: argparse.Namespace,
    schema: ProtocolSchema,
    state: NegotiationState,
    terms: dict,
    parties: dict,
    doc_hash: str,
    output_dir: Path,
    elapsed: float,
) -> None:
    """Poll until all parties have signed, then generate the executed PDF."""
    print(f"\n  {DIM}Waiting for all signatures (Ctrl+C to exit)...{RESET}", flush=True)
    timeout = args.poll_timeout if args.poll_timeout > 0 else 86400
    interval = 5

    try:
        elapsed_poll = 0
        while elapsed_poll < timeout:
            signers = _collect_all_signatures(args, schema, output_dir, quiet=True)

            # Check how many pending files exist (expected signers)
            expected = 0
            for role in ["founder", "investor"]:
                pf = output_dir / f"{schema.negotiation_id}_{role}_pending.txt"
                if pf.exists():
                    expected += 1

            if len(signers) >= expected and expected > 0:
                print(f"  {GREEN}All {len(signers)} signatures collected!{RESET}")
                break

            # Show status
            signed = [s["role"] for s in signers]
            pending = [r for r in ["founder", "investor"]
                       if (output_dir / f"{schema.negotiation_id}_{r}_pending.txt").exists()
                       and r not in signed]
            if pending:
                sys.stdout.write(f"\r  {DIM}Signed: {', '.join(signed) or 'none'}  |  Waiting: {', '.join(pending)}{RESET}   ")
                sys.stdout.flush()

            time.sleep(interval)
            elapsed_poll += interval
        else:
            print(f"\n\n  {DIM}Still waiting. Resume later with:{RESET}")
            print(f"  python negotiate.py --finalize all")
            return

    except KeyboardInterrupt:
        print(f"\n\n  {DIM}Interrupted. Resume later with:{RESET}")
        print(f"  python negotiate.py --finalize all")
        return

    _generate_executed_pdf(
        args, schema, state, terms, parties,
        doc_hash, signers, output_dir, elapsed,
    )


def _generate_executed_pdf(
    args: argparse.Namespace,
    schema: ProtocolSchema,
    state: NegotiationState,
    terms: dict,
    parties: dict,
    doc_hash: str,
    signers: list[dict],
    output_dir: Path,
    elapsed: float,
) -> None:
    """Generate the executed PDF with all collected signatures."""
    executed_path = str(output_dir / f"{schema.negotiation_id}_executed.pdf")
    exec_hash = generate_executed_document(
        doc_type=schema.document_type,
        terms=terms,
        parties=parties,
        output_path=executed_path,
        signers=signers,
        doc_hash=doc_hash,
        negotiation_history=state.history,
        negotiation_id=schema.negotiation_id,
        elapsed_seconds=elapsed,
    )

    print(f"\n  {TEAL}Executed:{RESET} {executed_path}")
    print(f"  {TEAL}SHA-256:{RESET}  {exec_hash}")
    for s in signers:
        has_hw = "handwritten" if s.get("signature_image") else "SSH"
        print(f"  {TEAL}{s['role']}:{RESET} {has_hw} signature embedded")

    # Auto-open the PDF
    import subprocess
    try:
        subprocess.Popen(["open", executed_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def handle_signing(
    args: argparse.Namespace,
    schema: ProtocolSchema,
    state: NegotiationState,
    agreed: dict,
    terms: dict,
    parties: dict,
    doc_hash: str,
    output_dir: Path,
    elapsed: float,
) -> None:
    """Handle the signing flow after agreement."""
    if args.no_sshsign or not args.signing_key_id:
        return

    session_id = getattr(args, "session_id", "") or ""
    role = getattr(args, "role", "") or ""

    try:
        sign_metadata = {
            "valuation_cap": agreed["valuation_cap"],
            "discount_rate": agreed["discount_rate"],
            "pro_rata": agreed["pro_rata"],
            "founder_name": args.founder_name,
            "founder_title": args.founder_title,
            "founder_company": args.company_name,
            "investor_name": args.investor_name,
            "investor_firm": args.investor_firm,
            "_signer_role": (role or "signer").capitalize(),
        }

        sign_result = sign_document(
            host=args.sshsign_host,
            key_id=args.signing_key_id,
            doc_type=schema.document_type,
            payload=doc_hash,
            metadata=sign_metadata,
            session_id=session_id or None,
        )
        logger.debug("sign_document response: %s", sign_result)

        if sign_result.get("error"):
            print(f"\n  {RED}Signing error: {sign_result['error']}{RESET}")
        elif sign_result.get("status") == "pending_cosign":
            pending_id = sign_result.get("pending_id")
            print(f"\n  {TEAL}Signing:{RESET}  pending cosign")
            print(f"  {TEAL}Pending:{RESET}  {pending_id}")
            if session_id:
                print(f"  {TEAL}Session:{RESET}  {session_id}")

            # Save pending_id so finalize can find both parties' signatures
            pending_file = output_dir / f"{schema.negotiation_id}_{role or 'party'}_pending.txt"
            pending_file.write_text(pending_id)

            approval_url = sign_result.get("approval_url")
            if sign_result.get("requires_signature") and approval_url:
                role_label = (role or "").upper() or "SIGNER"
                print(f"\n  {BOLD}Opening browser for {role_label} signature...{RESET}")
                webbrowser.open(approval_url)
            else:
                print(f"\n  Approve: ssh {args.sshsign_host} approve --id {pending_id}")

            if args.poll and pending_id:
                _poll_and_finalize(
                    args, schema, state, terms, parties,
                    doc_hash, output_dir, elapsed,
                )
        else:
            print(f"\n  {TEAL}Signature TX:{RESET} {sign_result.get('audit_tx_id')}")
    except Exception as e:
        logger.error("Failed to sign document: %s", e)
        print(f"\n  {RED}Signing failed: {e}{RESET}")


def handle_agreement(
    args: argparse.Namespace,
    schema: ProtocolSchema,
    state: NegotiationState,
    elapsed: float,
) -> None:
    """Handle post-agreement: generate document, log, sign."""
    agreed = state.agreed_terms()
    if not agreed:
        return

    print(f"{GREEN}{'='*60}{RESET}")
    print(f"  {BOLD}{GREEN}AGREEMENT REACHED{RESET}")
    print(f"{GREEN}{'='*60}{RESET}")
    print(f"  Valuation Cap:  ${agreed.get('valuation_cap', 0):>12,.0f}")
    print(f"  Discount Rate:  {agreed.get('discount_rate', 0):>12.0%}")
    print(f"  Pro-Rata:       {'Yes' if agreed.get('pro_rata') else 'No':>12}")
    print(f"  MFN:            {'Yes' if agreed.get('mfn') else 'No':>12}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(output_dir / f"{schema.negotiation_id}.pdf")

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    terms = {
        **agreed,
        "date": date,
        "investment_amount": args.investment_amount,
    }
    parties = {
        "founder": {
            "company": args.company_name,
            "name": args.founder_name,
            "title": args.founder_title,
        },
        "investor": {
            "name": args.investor_name,
            "firm": args.investor_firm,
        },
    }

    doc_hash = generate_document(
        doc_type=schema.document_type,
        terms=terms,
        parties=parties,
        output_path=pdf_path,
    )

    print(f"\n  {TEAL}Document:{RESET} {pdf_path}")
    print(f"  {TEAL}SHA-256:{RESET}  {doc_hash}")

    log_path = save_negotiation_log(state, schema, output_dir, elapsed, using_tokens=True)
    print(f"  {TEAL}Log:{RESET}      {log_path}")

    handle_signing(args, schema, state, agreed, terms, parties, doc_hash, output_dir, elapsed)


# ──────────────────────────────────────────────────────────
# Local mode: both agents in one process
# ──────────────────────────────────────────────────────────

async def run_local(args: argparse.Namespace) -> None:
    schema = ProtocolSchema.load(args.schema)
    if args.negotiation_id:
        schema.negotiation_id = args.negotiation_id
    state = NegotiationState(schema=schema)

    using_tokens = bool(args.founder_token and args.investor_token)

    if using_tokens:
        spinner_print("Loading APOA tokens...")
        founder_token, founder_constraints = load_apoa_token(
            args.founder_token, args.founder_pubkey,
        )
        investor_token, investor_constraints = load_apoa_token(
            args.investor_token, args.investor_pubkey,
        )
        print(f"  {DIM}Founder agent: {founder_token.definition.agent.id}{RESET}")
        print(f"  {DIM}Investor agent: {investor_token.definition.agent.id}{RESET}")
        print(f"  {DIM}Token expiry: {founder_token.definition.expires}{RESET}")
    else:
        founder_constraints, investor_constraints = build_constraints_from_args(args)

    founder_agent = ClaudeAgent(
        role="founder",
        constraints=founder_constraints,
        prompt_path=str(PROMPTS_DIR / "founder.txt"),
    )
    investor_agent = ClaudeAgent(
        role="investor",
        constraints=investor_constraints,
        prompt_path=str(PROMPTS_DIR / "investor.txt"),
    )

    agents = {"founder": founder_agent, "investor": investor_agent}
    constraints = {"founder": founder_constraints, "investor": investor_constraints}
    agent_histories: dict[str, list[dict]] = {"founder": [], "investor": []}

    previous_tx: int | None = None
    previous_terms: dict | None = None

    print_header(schema, state, using_tokens)

    negotiation_start = time.monotonic()

    while not state.terminated:
        current_role = state.whose_turn()
        agent = agents[current_role]
        agent_constraint = constraints[current_role]
        history = agent_histories[current_role]

        role_color = TEAL if current_role == "founder" else YELLOW
        sys.stdout.write(f"  {DIM}{role_color}{current_role}{RESET}{DIM} is thinking...{RESET}")
        sys.stdout.flush()

        offer = None
        for attempt in range(MAX_VALIDATION_RETRIES):
            raw_offer = await agent.make_offer(history)

            sys.stdout.write(f"\r{' '*40}\r")
            sys.stdout.flush()

            raw_offer["from"] = current_role
            raw_offer["negotiation_id"] = schema.negotiation_id
            raw_offer["round"] = state.current_round

            valid, reason = validate_offer_structure(raw_offer, schema)
            if not valid:
                logger.warning("Structure validation failed: %s (attempt %d)", reason, attempt + 1)
                history.append({
                    "role": "user",
                    "content": f"Your offer was invalid: {reason}. Please try again.",
                })
                sys.stdout.write(f"  {DIM}{role_color}{current_role}{RESET}{DIM} is revising...{RESET}")
                sys.stdout.flush()
                continue

            valid, reason = validate_offer_turn(raw_offer, state)
            if not valid:
                logger.warning("Turn validation failed: %s", reason)
                break

            if raw_offer["type"] in ("offer", "counter"):
                constraint_valid, violations = validate_apoa_constraints(
                    raw_offer["terms"], agent_constraint,
                )
                if not constraint_valid:
                    logger.warning("APOA constraint violation (attempt %d): %s", attempt + 1, violations)
                    history.append({
                        "role": "user",
                        "content": (
                            f"Your offer violates APOA constraints: {', '.join(violations)}. "
                            "Adjust your terms and try again."
                        ),
                    })
                    sys.stdout.write(f"  {DIM}{role_color}{current_role}{RESET}{DIM} is revising...{RESET}")
                    sys.stdout.flush()
                    continue
            else:
                constraint_valid, violations = True, []

            offer = raw_offer
            break

        if offer is None:
            print(f"\n{RED}{current_role.upper()} failed to produce a valid offer after {MAX_VALIDATION_RETRIES} attempts.{RESET}")
            print("Negotiation terminated.")
            return

        offer["timestamp"] = datetime.now(timezone.utc).isoformat()
        offer["apoa_validated"] = True

        if not args.no_sshsign:
            try:
                tx_result = log_offer(
                    host=args.sshsign_host,
                    negotiation_id=schema.negotiation_id,
                    round_num=state.current_round,
                    from_party=current_role,
                    offer_type=offer["type"],
                    metadata={**offer.get("terms", {}), "_message": offer.get("message", "")},
                    previous_tx=previous_tx,
                )
                offer["immudb_tx"] = tx_result.get("immudb_tx")
                previous_tx = offer["immudb_tx"]
            except Exception as e:
                logger.error("Failed to log offer to sshsign: %s", e)
                offer["immudb_tx"] = None

        display_offer(
            offer, current_role, state.current_round,
            (constraint_valid, violations), agent_constraint,
            previous_terms=previous_terms,
        )

        if offer.get("terms"):
            previous_terms = offer["terms"]

        state.record_offer(offer)

        other_role = "investor" if current_role == "founder" else "founder"
        agent_histories[current_role].append(offer)
        agent_histories[other_role].append(offer)

    elapsed = time.monotonic() - negotiation_start

    display_negotiation_summary(state, elapsed)

    if state.outcome == "accepted":
        handle_agreement(args, schema, state, elapsed)
    elif state.outcome == "rejected":
        print(f"\n{RED}One party rejected the negotiation.{RESET}")
    elif state.outcome == "max_rounds":
        print(f"\n{YELLOW}Max rounds ({state.max_rounds}) reached without agreement.{RESET}")

    print()


# ──────────────────────────────────────────────────────────
# Distributed mode: single agent, sshsign as shared state
# ──────────────────────────────────────────────────────────

async def run_distributed(args: argparse.Namespace) -> None:
    role = args.role
    other_role = "investor" if role == "founder" else "founder"

    schema = ProtocolSchema.load(args.schema)
    if args.negotiation_id:
        schema.negotiation_id = args.negotiation_id
    state = NegotiationState(schema=schema)

    # Load this party's token
    token_path = args.founder_token if role == "founder" else args.investor_token
    pubkey_path = args.founder_pubkey if role == "founder" else args.investor_pubkey

    if token_path:
        spinner_print(f"Loading {role} APOA token...")
        token, my_constraints = load_apoa_token(token_path, pubkey_path)
        print(f"  {DIM}Agent: {token.definition.agent.id}{RESET}")
        print(f"  {DIM}Token expiry: {token.definition.expires}{RESET}")
    else:
        if role == "founder":
            my_constraints = build_founder_constraints(
                cap_min=args.founder_cap_min,
                cap_max=args.founder_cap_max,
                discount_min=args.founder_discount_min,
                pro_rata_required=args.founder_pro_rata_required,
                mfn_required=args.founder_mfn_required,
            )
        else:
            my_constraints = build_investor_constraints(
                cap_min=args.investor_cap_min,
                cap_max=args.investor_cap_max,
                discount_min=args.investor_discount_min,
                discount_max=args.investor_discount_max,
                pro_rata_required=args.investor_pro_rata_required,
                mfn_required=args.investor_mfn_required,
            )

    prompt_path = str(PROMPTS_DIR / f"{role}.txt")
    agent = ClaudeAgent(role=role, constraints=my_constraints, prompt_path=prompt_path)

    print_header(schema, state, using_tokens=bool(token_path), role=role)

    negotiation_start = time.monotonic()
    agent_history: list[dict] = []
    previous_tx: int | None = None
    previous_terms: dict | None = None
    i_am_first = state.first_mover == role

    # Check if there's existing history (investor joining mid-negotiation)
    if not i_am_first:
        print(f"  {DIM}Waiting for {other_role}'s opening offer...{RESET}", flush=True)
        try:
            remote_history = poll_for_new_offer(
                host=args.sshsign_host,
                negotiation_id=schema.negotiation_id,
                expected_count=0,
                timeout=args.poll_timeout if args.poll_timeout > 0 else 86400,
            )
            # Replay existing offers into state
            for entry in remote_history:
                offer = _history_entry_to_offer(entry)
                display_offer(offer, offer["from"], offer.get("round", 0), (True, []), my_constraints, previous_terms)
                if offer.get("terms"):
                    previous_terms = offer["terms"]
                state.record_offer(offer)
                agent_history.append(offer)
        except TimeoutError:
            print(f"\n  {RED}Timed out waiting for {other_role}. Exiting.{RESET}")
            return

    while not state.terminated:
        current_turn = state.whose_turn()

        if current_turn == role:
            # My turn - generate an offer
            role_color = TEAL if role == "founder" else YELLOW
            sys.stdout.write(f"  {DIM}{role_color}{role}{RESET}{DIM} is thinking...{RESET}")
            sys.stdout.flush()

            offer = None
            for attempt in range(MAX_VALIDATION_RETRIES):
                raw_offer = await agent.make_offer(agent_history)

                sys.stdout.write(f"\r{' '*40}\r")
                sys.stdout.flush()

                raw_offer["from"] = role
                raw_offer["negotiation_id"] = schema.negotiation_id
                raw_offer["round"] = state.current_round

                valid, reason = validate_offer_structure(raw_offer, schema)
                if not valid:
                    logger.warning("Structure validation failed: %s (attempt %d)", reason, attempt + 1)
                    agent_history.append({
                        "role": "user",
                        "content": f"Your offer was invalid: {reason}. Please try again.",
                    })
                    sys.stdout.write(f"  {DIM}{role_color}{role}{RESET}{DIM} is revising...{RESET}")
                    sys.stdout.flush()
                    continue

                if raw_offer["type"] in ("offer", "counter"):
                    constraint_valid, violations = validate_apoa_constraints(
                        raw_offer["terms"], my_constraints,
                    )
                    if not constraint_valid:
                        logger.warning("APOA violation (attempt %d): %s", attempt + 1, violations)
                        agent_history.append({
                            "role": "user",
                            "content": (
                                f"Your offer violates APOA constraints: {', '.join(violations)}. "
                                "Adjust your terms and try again."
                            ),
                        })
                        sys.stdout.write(f"  {DIM}{role_color}{role}{RESET}{DIM} is revising...{RESET}")
                        sys.stdout.flush()
                        continue
                else:
                    constraint_valid, violations = True, []

                offer = raw_offer
                break

            if offer is None:
                print(f"\n{RED}Failed to produce a valid offer after {MAX_VALIDATION_RETRIES} attempts.{RESET}")
                return

            offer["timestamp"] = datetime.now(timezone.utc).isoformat()
            offer["apoa_validated"] = True

            # Log to sshsign
            try:
                tx_result = log_offer(
                    host=args.sshsign_host,
                    negotiation_id=schema.negotiation_id,
                    round_num=state.current_round,
                    from_party=role,
                    offer_type=offer["type"],
                    metadata={**offer.get("terms", {}), "_message": offer.get("message", "")},
                    previous_tx=previous_tx,
                )
                offer["immudb_tx"] = tx_result.get("immudb_tx")
                previous_tx = offer["immudb_tx"]
            except Exception as e:
                logger.error("Failed to log offer: %s", e)
                offer["immudb_tx"] = None

            display_offer(
                offer, role, state.current_round,
                (constraint_valid, violations), my_constraints,
                previous_terms=previous_terms,
            )

            if offer.get("terms"):
                previous_terms = offer["terms"]

            state.record_offer(offer)
            agent_history.append(offer)

        else:
            # Other party's turn - poll for their offer
            print(f"  {DIM}Waiting for {other_role}...{RESET}", flush=True)
            try:
                remote_history = poll_for_new_offer(
                    host=args.sshsign_host,
                    negotiation_id=schema.negotiation_id,
                    expected_count=len(state.history),
                    timeout=args.poll_timeout if args.poll_timeout > 0 else 86400,
                )
                # Find the new offer(s)
                new_entries = remote_history[len(state.history):]
                for entry in new_entries:
                    offer = _history_entry_to_offer(entry)

                    display_offer(offer, offer["from"], offer.get("round", 0), (True, []), my_constraints, previous_terms)

                    if offer.get("terms"):
                        previous_terms = offer["terms"]

                    state.record_offer(offer)
                    agent_history.append(offer)

            except TimeoutError:
                print(f"\n  {YELLOW}Timed out waiting for {other_role}.{RESET}")
                return

    elapsed = time.monotonic() - negotiation_start

    display_negotiation_summary(state, elapsed)

    if state.outcome == "accepted":
        handle_agreement(args, schema, state, elapsed)
    elif state.outcome == "rejected":
        print(f"\n{RED}Negotiation rejected.{RESET}")
    elif state.outcome == "max_rounds":
        print(f"\n{YELLOW}Max rounds ({state.max_rounds}) reached.{RESET}")

    print()


def _history_entry_to_offer(entry: dict) -> dict:
    """Convert a sshsign history entry to the offer dict format used by NegotiationState."""
    metadata = entry.get("metadata", "{}")
    if isinstance(metadata, str):
        terms = json.loads(metadata)
    else:
        terms = metadata

    # Extract message from metadata (stored as _message)
    message = terms.pop("_message", "")

    return {
        "from": entry.get("from", ""),
        "type": entry.get("type", ""),
        "round": entry.get("round", 0),
        "terms": terms,
        "message": message,
        "immudb_tx": entry.get("audit_tx_id"),
        "timestamp": entry.get("created_at", ""),
        "apoa_validated": True,
    }


# ──────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────
# Finalize mode: fetch envelope and generate executed PDF
# ──────────────────────────────────────────────────────────

def run_finalize(args: argparse.Namespace) -> None:
    """Collect all signatures and generate the executed PDF."""
    neg_id = args.negotiation_id

    print(f"\n{TEAL}{'='*60}{RESET}")
    print(f"  {BOLD}Finalizing{RESET}")
    print(f"{TEAL}{'='*60}{RESET}")
    if neg_id:
        print(f"  Negotiation   {neg_id}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # If a specific pending ID was given (legacy), handle it
    # If "all" was given, collect all signatures from pending files
    if args.finalize != "all":
        # Single pending ID - wait for it if needed, then collect all
        from sshsign_client import get_envelope
        pending_id = args.finalize
        print(f"  Pending ID    {pending_id}")

        result = get_envelope(host=args.sshsign_host, pending_id=pending_id)
        if result.get("status") == "pending":
            print(f"\n  {YELLOW}Waiting for approval...{RESET}", flush=True)
            try:
                poll_for_approval(
                    host=args.sshsign_host,
                    pending_id=pending_id,
                    timeout=args.poll_timeout if args.poll_timeout > 0 else 86400,
                )
            except (KeyboardInterrupt, TimeoutError):
                print(f"\n  {DIM}Still pending. Try again later.{RESET}")
                return

    # Load negotiation history
    if neg_id:
        history_raw = get_history(host=args.sshsign_host, negotiation_id=neg_id)
        history = [_history_entry_to_offer(e) for e in history_raw] if isinstance(history_raw, list) else []
    else:
        history = []

    # Get agreed terms
    agreed = None
    if len(history) >= 2:
        agreed = history[-2].get("terms")

    if not agreed:
        print(f"\n  {RED}Could not determine agreed terms from history.{RESET}")
        return

    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    terms = {
        **agreed,
        "date": date,
        "investment_amount": args.investment_amount,
    }
    parties = {
        "founder": {
            "company": args.company_name,
            "name": args.founder_name,
            "title": args.founder_title,
        },
        "investor": {
            "name": args.investor_name,
            "firm": args.investor_firm,
        },
    }

    # Generate unsigned PDF for the hash
    pdf_path = str(output_dir / f"{neg_id}.pdf")
    doc_hash = generate_document(
        doc_type="safe-agreement",
        terms=terms,
        parties=parties,
        output_path=pdf_path,
    )

    # Collect all signatures
    schema = ProtocolSchema.load(args.schema)
    schema.negotiation_id = neg_id
    state = NegotiationState(schema=schema)
    for offer in history:
        state.record_offer(offer)

    print(f"\n  {DIM}Collecting signatures...{RESET}")
    signers = _collect_all_signatures(args, schema, output_dir)

    if not signers:
        print(f"\n  {YELLOW}No approved signatures found yet.{RESET}")
        return

    _generate_executed_pdf(
        args, schema, state, terms, parties,
        doc_hash, signers, output_dir, elapsed=0,
    )

    print()


# ──────────────────────────────────────────────────────────
# Auto setup: create tokens and signing keys from .env
# ──────────────────────────────────────────────────────────

def auto_setup(args: argparse.Namespace) -> argparse.Namespace:
    """Create APOA tokens and sshsign signing keys if not already set up."""
    from apoa import (
        APOADefinition, Agent, Principal, ServiceAuthorization,
        SigningOptions, create_client, generate_key_pair,
    )
    from sshsign_client import create_signing_key

    keys_dir = Path("keys")
    keys_dir.mkdir(parents=True, exist_ok=True)
    tokens_dir = Path("tokens")
    tokens_dir.mkdir(parents=True, exist_ok=True)

    role = getattr(args, "role", "") or ""
    roles_to_setup = [role] if role else ["founder", "investor"]

    print(f"\n  {DIM}Setting up...{RESET}")

    client = create_client()

    # Generate or discover negotiation ID
    neg_id_file = Path("output/.negotiation_id")
    Path("output").mkdir(parents=True, exist_ok=True)

    if args.negotiation_id:
        pass  # Explicitly set via .env or CLI
    elif role == "investor" and neg_id_file.exists():
        # Investor picks up the founder's negotiation ID
        args.negotiation_id = neg_id_file.read_text().strip()
        spinner_print(f"Found negotiation: {args.negotiation_id}")
    elif role == "investor" and not neg_id_file.exists():
        # Wait for the founder to create it
        print(f"  {DIM}Waiting for founder to start the negotiation...{RESET}", flush=True)
        timeout = 300
        elapsed = 0
        while elapsed < timeout:
            if neg_id_file.exists():
                args.negotiation_id = neg_id_file.read_text().strip()
                spinner_print(f"Found negotiation: {args.negotiation_id}")
                break
            time.sleep(1)
            elapsed += 1
        else:
            print(f"\n  {RED}Timed out waiting for founder.{RESET}")
            print(f"  Make sure the founder runs first, or set NEGOTIATION_ID in .env\n")
            raise RuntimeError("No negotiation ID")
    else:
        # Founder (or local mode) generates a new ID
        args.negotiation_id = f"neg_{uuid_mod.uuid4().hex[:12]}"
        neg_id_file.write_text(args.negotiation_id)

    if not args.session_id:
        args.session_id = f"session_{args.negotiation_id}"

    for r in roles_to_setup:
        priv_path = keys_dir / f"{r}_private.pem"
        pub_path = keys_dir / f"{r}_public.pem"

        # Generate Ed25519 key pair for APOA token
        if priv_path.exists():
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            private_key = load_pem_private_key(priv_path.read_bytes(), password=None)
        else:
            private_key, public_key = generate_key_pair("EdDSA")
            from cryptography.hazmat.primitives import serialization
            priv_path.write_bytes(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ))
            pub_path.write_bytes(public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ))

        # Build APOA token
        if r == "founder":
            constraints = {
                "valuation_cap_min": args.founder_cap_min,
                "valuation_cap_max": args.founder_cap_max,
                "discount_rate_min": args.founder_discount_min,
                "discount_rate_max": args.founder_discount_max,
                "pro_rata_required": args.founder_pro_rata_required,
                "mfn_required": args.founder_mfn_required,
            }
        else:
            constraints = {
                "valuation_cap_min": args.investor_cap_min,
                "valuation_cap_max": args.investor_cap_max,
                "discount_rate_min": args.investor_discount_min,
                "discount_rate_max": args.investor_discount_max,
                "pro_rata_required": args.investor_pro_rata_required,
                "mfn_required": args.investor_mfn_required,
            }

        definition = APOADefinition(
            principal=Principal(id="did:apoa:principal", name=f"{r.capitalize()} Principal"),
            agent=Agent(id=f"did:apoa:{r}-agent", name=f"{r.capitalize()}Negotiator"),
            services=[
                ServiceAuthorization(
                    service="safe-agreement",
                    scopes=["offer:submit", "offer:accept", "document:sign"],
                    constraints=constraints,
                )
            ],
            expires="2026-12-31T23:59:59Z",
            revocable=True,
            delegatable=False,
        )

        token = client.create_token(definition, SigningOptions(private_key=private_key))
        (tokens_dir / f"{r}.jwt").write_text(token.raw)
        spinner_print(f"APOA token for {r}")

        # Set token/pubkey paths on args
        if r == "founder":
            args.founder_token = str(tokens_dir / "founder.jwt")
            args.founder_pubkey = str(keys_dir / "founder_public.pem")
        else:
            args.investor_token = str(tokens_dir / "investor.jwt")
            args.investor_pubkey = str(keys_dir / "investor_public.pem")

        # Create sshsign signing key using this party's constraints
        signing_key_attr = f"{r}_signing_key_id"
        if not getattr(args, signing_key_attr, "") and not args.no_sshsign:
            if r == "founder":
                sshsign_constraints = {
                    "valuation_cap": {"min": args.founder_cap_min, "max": args.founder_cap_max},
                    "discount_rate": {"min": args.founder_discount_min, "max": args.founder_discount_max},
                    "pro_rata": {"required": args.founder_pro_rata_required},
                }
            else:
                sshsign_constraints = {
                    "valuation_cap": {"min": args.investor_cap_min, "max": args.investor_cap_max},
                    "discount_rate": {"min": args.investor_discount_min, "max": args.investor_discount_max},
                    "pro_rata": {"required": args.investor_pro_rata_required},
                }
            req_sig = args.founder_require_signature if r == "founder" else args.investor_require_signature
            result = create_signing_key(
                host=args.sshsign_host,
                scope="safe-agreement",
                tier="cosign",
                constraints=sshsign_constraints,
                require_signature=req_sig,
            )
            key_id = result["key_id"]
            setattr(args, signing_key_attr, key_id)
            spinner_print(f"Signing key for {r}: {key_id}")

    # Set signing_key_id based on role
    if role == "founder":
        args.signing_key_id = args.founder_signing_key_id
    elif role == "investor":
        args.signing_key_id = args.investor_signing_key_id
    elif not role:
        # Local mode: use the founder's key for signing
        args.signing_key_id = args.founder_signing_key_id

    # For single-party mode, print the neg ID to share
    if role == "founder":
        print()
        print(f"  {TEAL}{'─'*50}{RESET}")
        print(f"  {BOLD}Send this to the investor:{RESET}")
        print()
        print(f"    NEGOTIATION_ID={args.negotiation_id}")
        print()
        print(f"  {DIM}They add it to their .env and run:{RESET}")
        print(f"  {DIM}python negotiate.py --poll{RESET}")
        print(f"  {TEAL}{'─'*50}{RESET}")

    print()
    return args


# ──────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────

def _check_prerequisites() -> bool:
    """Check that all required dependencies and config are in place."""
    errors = []

    # Check .env exists
    if not Path(".env").exists():
        if Path(".env.example").exists():
            print(f"\n  {YELLOW}No .env file found.{RESET}")
            print(f"  Run: {BOLD}cp .env.example .env{RESET}")
            print(f"  Then edit .env with your details.\n")
            return False
        else:
            print(f"\n  {YELLOW}No .env or .env.example found.{RESET}")
            print(f"  Are you in the negotiate project directory?\n")
            return False

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or api_key == "your-api-key-here":
        print(f"\n  {RED}Missing Anthropic API key.{RESET}")
        print(f"  1. Get a key at {BOLD}https://console.anthropic.com/{RESET}")
        print(f"  2. Add it to your .env file:")
        print(f"     {DIM}ANTHROPIC_API_KEY=sk-ant-...{RESET}\n")
        return False

    # Check apoa SDK
    try:
        import apoa
    except ImportError:
        print(f"\n  {RED}Missing APOA Python SDK.{RESET}")
        print(f"  Run: {BOLD}pip install apoa{RESET}\n")
        return False

    # Check anthropic SDK
    try:
        import anthropic
    except ImportError:
        print(f"\n  {RED}Missing Anthropic SDK.{RESET}")
        print(f"  Run: {BOLD}pip install -r requirements.txt{RESET}\n")
        return False

    return True


def _check_role_config(args: argparse.Namespace) -> bool:
    """Check role-specific config."""
    return True


def main() -> None:
    args = parse_args()

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("fontTools").setLevel(logging.WARNING)
        logging.getLogger("fpdf").setLevel(logging.WARNING)

    # Finalize mode
    if args.finalize:
        args = auto_setup(args)
        run_finalize(args)
        return

    # Check prerequisites
    if not _check_prerequisites():
        return

    if not _check_role_config(args):
        return

    try:
        args = auto_setup(args)
    except RuntimeError as e:
        err = str(e)
        if "sshsign command failed" in err:
            print(f"\n  {RED}Could not connect to sshsign.dev{RESET}")
            print(f"  Make sure you have SSH access:")
            print(f"     {BOLD}ssh sshsign.dev{RESET}")
            print(f"  If this is your first time, you need an SSH key:")
            print(f"     {DIM}ssh-keygen -t ed25519{RESET}")
            print(f"     Then try: {DIM}ssh sshsign.dev{RESET}\n")
        else:
            print(f"\n  {RED}Setup failed: {err}{RESET}\n")
        return
    except Exception as e:
        print(f"\n  {RED}Setup failed: {e}{RESET}\n")
        return

    role = getattr(args, "role", "") or ""
    try:
        if role:
            asyncio.run(run_distributed(args))
        else:
            asyncio.run(run_local(args))
    except TypeError as e:
        if "authentication method" in str(e).lower():
            print(f"\n  {RED}Invalid Anthropic API key.{RESET}")
            print(f"  Check your .env file - the key may be expired or malformed.")
            print(f"  Get a new key at {BOLD}https://console.anthropic.com/{RESET}\n")
        else:
            raise


if __name__ == "__main__":
    main()
