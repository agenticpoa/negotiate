"""
Create signed APOA tokens and config files for SAFE negotiation.

Two modes:
  1. Both parties (default): generates tokens and configs for founder + investor
  2. Single party (--role): generates token and config for one party only

Single-party mode lets each person set up independently on their own machine.
The founder generates a negotiation ID and shares it with the investor.
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from apoa import (
    APOADefinition,
    Agent,
    Principal,
    ServiceAuthorization,
    SigningOptions,
    create_client,
    generate_key_pair,
)


def parse_args() -> argparse.Namespace:
    def env(key: str, default: str = "") -> str:
        return os.environ.get(key, default)

    def env_int(key: str, default: int) -> int:
        v = os.environ.get(key)
        return int(v) if v else default

    def env_float(key: str, default: float) -> float:
        v = os.environ.get(key)
        return float(v) if v else default

    def env_bool(key: str, default: bool) -> bool:
        v = os.environ.get(key)
        return v.lower() in ("true", "1", "yes") if v else default

    parser = argparse.ArgumentParser(
        description="Create APOA tokens and config files for SAFE negotiation",
    )
    # Mode
    parser.add_argument("--role", default=env("ROLE"), choices=["", "founder", "investor"],
                        help="Single-party mode: generate config for one party only")
    parser.add_argument("--negotiation-id", default=env("NEGOTIATION_ID"),
                        help="Existing negotiation ID (required for investor in single-party mode)")

    # Directories
    parser.add_argument("--keys-dir", default="keys")
    parser.add_argument("--tokens-dir", default="tokens")
    parser.add_argument("--config-dir", default=".")

    # Founder info
    parser.add_argument("--founder-name", default=env("FOUNDER_NAME", "Jane Doe"))
    parser.add_argument("--founder-title", default=env("FOUNDER_TITLE", "CEO"))
    parser.add_argument("--company-name", default=env("COMPANY_NAME", "Acme Corp"))
    parser.add_argument("--founder-signing-key-id", default=env("FOUNDER_SIGNING_KEY_ID"))

    # Founder constraints
    parser.add_argument("--founder-cap-min", type=int, default=env_int("FOUNDER_CAP_MIN", 8_000_000))
    parser.add_argument("--founder-cap-max", type=int, default=env_int("FOUNDER_CAP_MAX", 12_000_000))
    parser.add_argument("--founder-discount-min", type=float, default=env_float("FOUNDER_DISCOUNT_MIN", 0.20))
    parser.add_argument("--founder-discount-max", type=float, default=env_float("FOUNDER_DISCOUNT_MAX", 0.25))
    parser.add_argument("--founder-pro-rata-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("FOUNDER_PRO_RATA_REQUIRED", True))
    parser.add_argument("--founder-mfn-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("FOUNDER_MFN_REQUIRED", False))

    # Investor info
    parser.add_argument("--investor-name", default=env("INVESTOR_NAME", "Angel Ventures"))
    parser.add_argument("--investor-firm", default=env("INVESTOR_FIRM", ""))
    parser.add_argument("--investor-signing-key-id", default=env("INVESTOR_SIGNING_KEY_ID"))

    # Investor constraints
    parser.add_argument("--investor-cap-min", type=int, default=env_int("INVESTOR_CAP_MIN", 6_000_000))
    parser.add_argument("--investor-cap-max", type=int, default=env_int("INVESTOR_CAP_MAX", 10_000_000))
    parser.add_argument("--investor-discount-min", type=float, default=env_float("INVESTOR_DISCOUNT_MIN", 0.15))
    parser.add_argument("--investor-discount-max", type=float, default=env_float("INVESTOR_DISCOUNT_MAX", 0.25))
    parser.add_argument("--investor-pro-rata-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("INVESTOR_PRO_RATA_REQUIRED", False))
    parser.add_argument("--investor-mfn-required", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("INVESTOR_MFN_REQUIRED", False))

    # Shared settings
    parser.add_argument("--investment-amount", type=float, default=env_float("INVESTMENT_AMOUNT", 500_000.0))
    # sshsign
    parser.add_argument("--sshsign-host", default=env("SSHSIGN_HOST", "sshsign.dev"))
    parser.add_argument("--create-keys", action="store_true",
                        help="Create signing keys on sshsign automatically")
    parser.add_argument("--founder-require-signature", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("FOUNDER_REQUIRE_SIGNATURE", True))
    parser.add_argument("--investor-require-signature", type=lambda v: v.lower() in ("true", "1", "yes"),
                        default=env_bool("INVESTOR_REQUIRE_SIGNATURE", True))

    parser.add_argument("--expires", default="2026-05-02T23:59:59Z")
    parser.add_argument("--principal-id", default="did:apoa:principal")
    parser.add_argument("--schema", default="schemas/safe.json")
    return parser.parse_args()


def save_key(key, path: Path) -> None:
    from cryptography.hazmat.primitives import serialization

    if hasattr(key, "private_bytes"):
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        pem = key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    path.write_bytes(pem)


def load_private_key(path: Path):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    return load_pem_private_key(path.read_bytes(), password=None)


def generate_or_load_keys(keys_dir: Path, role: str):
    """Generate or load an Ed25519 key pair for a role."""
    priv_path = keys_dir / f"{role}_private.pem"
    pub_path = keys_dir / f"{role}_public.pem"

    if priv_path.exists():
        print(f"Loading existing {role} keys...")
        private = load_private_key(priv_path)
    else:
        print(f"Generating {role} key pair...")
        private, public = generate_key_pair("EdDSA")
        save_key(private, priv_path)
        save_key(public, pub_path)

    return private


def create_token_for_role(client, role: str, args, private_key, tokens_dir: Path):
    """Create and save an APOA token for a role."""
    if role == "founder":
        constraints = {
            "valuation_cap_min": args.founder_cap_min,
            "valuation_cap_max": args.founder_cap_max,
            "discount_rate_min": args.founder_discount_min,
            "discount_rate_max": args.founder_discount_max,
            "pro_rata_required": args.founder_pro_rata_required,
            "mfn_required": args.founder_mfn_required,
        }
        agent_id = "did:apoa:founder-agent"
        agent_name = "FounderNegotiator"
        principal_name = "Founder Principal"
    else:
        constraints = {
            "valuation_cap_min": args.investor_cap_min,
            "valuation_cap_max": args.investor_cap_max,
            "discount_rate_min": args.investor_discount_min,
            "discount_rate_max": args.investor_discount_max,
            "pro_rata_required": args.investor_pro_rata_required,
            "mfn_required": args.investor_mfn_required,
        }
        agent_id = "did:apoa:investor-agent"
        agent_name = "InvestorNegotiator"
        principal_name = "Investor Principal"

    definition = APOADefinition(
        principal=Principal(id=args.principal_id, name=principal_name),
        agent=Agent(id=agent_id, name=agent_name),
        services=[
            ServiceAuthorization(
                service="safe-agreement",
                scopes=["offer:submit", "offer:accept", "document:sign"],
                constraints=constraints,
            )
        ],
        expires=args.expires,
        revocable=True,
        delegatable=False,
    )

    token = client.create_token(definition, SigningOptions(private_key=private_key))
    (tokens_dir / f"{role}.jwt").write_text(token.raw)

    return definition, token


def build_config(role: str, args, negotiation_id: str, session_id: str, keys_dir: Path, tokens_dir: Path) -> dict:
    """Build a config dict for a role."""
    shared = {
        "negotiation_id": negotiation_id,
        "session_id": session_id,
        "schema": args.schema,
        "sshsign_host": args.sshsign_host,
        "investment_amount": args.investment_amount,
        "company_name": args.company_name,
        "date": "",
        "founder_signing_key_id": args.founder_signing_key_id,
        "investor_signing_key_id": args.investor_signing_key_id,
    }

    if role == "founder":
        return {
            **shared,
            "role": "founder",
            "token": str(tokens_dir / "founder.jwt"),
            "pubkey": str(keys_dir / "founder_public.pem"),
            "signing_key_id": args.founder_signing_key_id,
            "name": args.founder_name,
            "title": args.founder_title,
            "party_name": args.founder_name,
            "investor_name": args.investor_name,
        }
    else:
        return {
            **shared,
            "role": "investor",
            "token": str(tokens_dir / "investor.jwt"),
            "pubkey": str(keys_dir / "investor_public.pem"),
            "signing_key_id": args.investor_signing_key_id,
            "name": args.investor_name,
            "party_name": args.investor_name,
            "founder_name": args.founder_name,
            "founder_title": args.founder_title,
        }


def create_sshsign_key(args, role: str) -> str:
    """Create a signing key on sshsign using the party's own constraints."""
    from sshsign_client import create_signing_key

    if role == "founder":
        constraints = {
            "valuation_cap": {"min": args.founder_cap_min, "max": args.founder_cap_max},
            "discount_rate": {"min": args.founder_discount_min, "max": args.founder_discount_max},
            "pro_rata": {"required": args.founder_pro_rata_required},
        }
    else:
        constraints = {
            "valuation_cap": {"min": args.investor_cap_min, "max": args.investor_cap_max},
            "discount_rate": {"min": args.investor_discount_min, "max": args.investor_discount_max},
            "pro_rata": {"required": args.investor_pro_rata_required},
        }

    label = role.capitalize()
    print(f"  Creating {label} signing key on {args.sshsign_host}...")
    result = create_signing_key(
        host=args.sshsign_host,
        scope="safe-agreement",
        tier="cosign",
        constraints=constraints,
        require_signature=args.founder_require_signature if role == "founder" else args.investor_require_signature,
    )
    key_id = result["key_id"]
    print(f"  {label} key: {key_id}")
    return key_id


def main() -> None:
    args = parse_args()

    keys_dir = Path(args.keys_dir)
    keys_dir.mkdir(parents=True, exist_ok=True)
    tokens_dir = Path(args.tokens_dir)
    tokens_dir.mkdir(parents=True, exist_ok=True)
    config_dir = Path(args.config_dir)

    client = create_client()
    single_party = args.role

    # Create signing keys on sshsign if requested
    if args.create_keys:
        if single_party == "founder" or not single_party:
            if not args.founder_signing_key_id:
                args.founder_signing_key_id = create_sshsign_key(args, "founder")
        if single_party == "investor" or not single_party:
            if not args.investor_signing_key_id:
                args.investor_signing_key_id = create_sshsign_key(args, "investor")
        print()

    # Determine negotiation ID
    if args.negotiation_id:
        negotiation_id = args.negotiation_id
    else:
        negotiation_id = f"neg_{uuid.uuid4().hex[:12]}"

    session_id = f"session_{negotiation_id}"

    if single_party == "investor" and not args.negotiation_id:
        print("Error: --negotiation-id is required when --role investor")
        print("The founder generates the negotiation ID. Ask them for it.")
        return

    # ── Single-party mode ──────────────────────────────────

    if single_party:
        private_key = generate_or_load_keys(keys_dir, single_party)
        definition, token = create_token_for_role(client, single_party, args, private_key, tokens_dir)

        config = build_config(single_party, args, negotiation_id, session_id, keys_dir, tokens_dir)
        config_path = config_dir / f"{single_party}.json"
        config_path.write_text(json.dumps(config, indent=2))

        name = args.founder_name if single_party == "founder" else args.investor_name
        print(f"\n  Negotiation   {negotiation_id}")
        print(f"\n  Role:         {single_party.capitalize()}")
        print(f"  Name:         {name}")
        for k, v in definition.services[0].constraints.items():
            print(f"                {k}: {v}")

        print(f"\n  Files:")
        print(f"    {config_path}")
        print(f"    {tokens_dir}/{single_party}.jwt")
        print(f"    {keys_dir}/{single_party}_public.pem")

        if single_party == "founder":
            print(f"\n  Share this negotiation ID with the investor:")
            print(f"    {negotiation_id}")

        print(f"\n  Run:")
        print(f"    python negotiate.py --config {single_party}.json --poll")
        return

    # ── Both parties mode ──────────────────────────────────

    founder_private = generate_or_load_keys(keys_dir, "founder")
    investor_private = generate_or_load_keys(keys_dir, "investor")

    founder_def, _ = create_token_for_role(client, "founder", args, founder_private, tokens_dir)
    investor_def, _ = create_token_for_role(client, "investor", args, investor_private, tokens_dir)

    # Write configs
    founder_config = build_config("founder", args, negotiation_id, session_id, keys_dir, tokens_dir)
    (config_dir / "founder.json").write_text(json.dumps(founder_config, indent=2))

    investor_config = build_config("investor", args, negotiation_id, session_id, keys_dir, tokens_dir)
    (config_dir / "investor.json").write_text(json.dumps(investor_config, indent=2))

    # Print summary
    print(f"\n  Negotiation   {negotiation_id}")
    print(f"\n  Founder:      {args.founder_name} ({args.founder_title})")
    for k, v in founder_def.services[0].constraints.items():
        print(f"                {k}: {v}")

    print(f"\n  Investor:     {args.investor_name}")
    for k, v in investor_def.services[0].constraints.items():
        print(f"                {k}: {v}")

    print(f"\n  Expires:      {args.expires}")
    print(f"\n  Files:")
    print(f"    founder.json")
    print(f"    investor.json")
    print(f"    {tokens_dir}/")
    print(f"    {keys_dir}/")

    print(f"\n  Run:")
    print(f"    Terminal 1:  python negotiate.py --config founder.json --poll")
    print(f"    Terminal 2:  python negotiate.py --config investor.json --poll")


if __name__ == "__main__":
    main()
