# negotiate

AI agents that negotiate YC SAFEs. You set the boundaries. They find the deal.

Every offer is cryptographically signed, constraint-validated, and logged to a tamper-proof audit trail. When the agents agree, you review the terms and draw your signature in the browser. Out comes an executed PDF with the full negotiation history.

## Try it in 60 seconds

No sshsign account needed. Just watch two agents negotiate:

```bash
git clone git@github.com:agenticpoa/negotiate.git
cd negotiate
pip install -r requirements.txt
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
python negotiate.py --no-sshsign
```

## Full setup (with signing)

### Prerequisites

- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)
- SSH key (`ssh-keygen -t ed25519` if you don't have one)

### Install

```bash
pip install -r requirements.txt
cp .env.example .env
```

### Configure

Open `.env` and fill in your details. The file is organized into sections:

- **Required** -- your Anthropic API key
- **Party names** -- company and people
- **Founder Settings** -- the founder's negotiation constraints and signing preferences
- **Investor Settings** -- the investor's negotiation constraints and signing preferences

For a quick test, just add your API key and party names. The constraint defaults work out of the box.

### Run

```bash
python negotiate.py --poll
```

The script handles everything:
1. Creates APOA authorization tokens for both agents
2. Creates signing keys on [sshsign.dev](https://sshsign.dev)
3. Runs the negotiation (agents alternate offers within constraints)
4. Opens your browser for handwritten signature
5. Generates the executed PDF

The `--poll` flag tells the script to wait for your signature after the negotiation completes. Without it, the script exits after submitting the signing request.

---

## Two-party mode

Founder and investor each run their own agent. The agents negotiate through [sshsign.dev](https://sshsign.dev) as the shared relay.

### On the same machine (two terminals)

Both terminals share the same `.env`. Use `--role` to pick a side:

```bash
cp .env.example .env
# Edit .env with both parties' details (leave ROLE= blank)
```

**Terminal 1 (start first):**
```bash
python negotiate.py --role founder --poll
```

**Terminal 2:**
```bash
python negotiate.py --role investor --poll
```

The investor automatically picks up the founder's negotiation ID.

### On separate machines

Each party clones the repo, edits their section of `.env`, and runs. The only thing shared is a negotiation ID.

**Founder:**
```bash
git clone git@github.com:agenticpoa/negotiate.git
cd negotiate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` -- fill in the top section and the **Founder Settings** section. Ignore the Investor Settings (they don't affect you):
```
ANTHROPIC_API_KEY=your-key
ROLE=founder
COMPANY_NAME=Acme Labs
FOUNDER_NAME=Alice Chen
FOUNDER_TITLE=CEO

# Under FOUNDER SETTINGS:
FOUNDER_CAP_MIN=8000000
FOUNDER_CAP_MAX=12000000
# ... adjust your constraints
```

```bash
python negotiate.py --poll
```

The script prints a negotiation ID. Send it to the investor.

**Investor:**
```bash
git clone git@github.com:agenticpoa/negotiate.git
cd negotiate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` -- fill in the top section and the **Investor Settings** section. Ignore the Founder Settings (they don't affect you):
```
ANTHROPIC_API_KEY=your-key
ROLE=investor
NEGOTIATION_ID=neg_abc123
INVESTOR_NAME=Bay Capital

# Under INVESTOR SETTINGS:
INVESTOR_CAP_MIN=6000000
INVESTOR_CAP_MAX=10000000
# ... adjust your constraints
```

```bash
python negotiate.py --poll
```

### Signing

When the agents agree, a browser tab opens for each party. Draw your signature, click "Sign & Approve". The script waits for both, then generates the executed PDF.

If you close the terminal before signing, resume anytime:

```bash
python negotiate.py --finalize all
```

---

## What's in the executed PDF

| Page | Contents |
|------|----------|
| 1-2 | SAFE agreement (YC post-money standard) with negotiated terms |
| 3 | Signature page with handwritten signatures from both parties |
| 4 | Negotiation audit trail: offer table, timestamps, immudb TX IDs, full transcript |
| 5 | Certificate of Execution: document hash, signing keys, SSH signature blocks |

## How the protocol works

Based on the [Rubinstein alternating offers model](https://en.wikipedia.org/wiki/Rubinstein_bargaining_model) (Econometrica, 1982). Two agents take turns making offers. Each offer is:

1. **Validated** against the agent's APOA token constraints (can't go outside authorized range)
2. **Logged** to sshsign/immudb with Merkle tree chain linking (tamper-proof)
3. **Displayed** with constraint proximity hints (how close to the floor/ceiling)

The negotiation ends when one agent accepts, rejects, or max rounds (10) is reached.

## Customizing constraints

Edit `.env`:

| Variable | What it controls | Default |
|----------|-----------------|---------|
| `FOUNDER_CAP_MIN` | Minimum valuation cap founder will accept | $8M |
| `FOUNDER_CAP_MAX` | Maximum valuation cap founder will propose | $12M |
| `FOUNDER_DISCOUNT_MIN` | Minimum discount rate founder requires | 20% |
| `FOUNDER_DISCOUNT_MAX` | Maximum discount rate founder will accept | 25% |
| `FOUNDER_PRO_RATA_REQUIRED` | Founder requires pro-rata rights | true |
| `FOUNDER_MFN_REQUIRED` | Founder requires MFN clause | false |
| `INVESTOR_CAP_MIN` | Lowest cap investor will offer | $6M |
| `INVESTOR_CAP_MAX` | Highest cap investor will go | $10M |
| `INVESTOR_DISCOUNT_MIN` | Minimum discount investor offers | 15% |
| `INVESTOR_DISCOUNT_MAX` | Maximum discount investor will accept | 25% |
| `INVESTOR_PRO_RATA_REQUIRED` | Investor requires pro-rata rights | false |
| `INVESTOR_MFN_REQUIRED` | Investor requires MFN clause | false |

Each party's signing key on sshsign automatically uses their own constraints. Two layers of protection per party: the APOA token constrains the agent, the signing key constrains the signature.

## Architecture

```
negotiate.py          One command to run everything
protocol.py           Offer validation, turn tracking, APOA constraint checks
sshsign_client.py     SSH communication with sshsign.dev
agents/               Claude-powered negotiation agents
documents/            PDF generation (YC SAFE template)
prompts/              Agent system prompts (parameterized)
schemas/              Protocol definition (JSON)
```

## Credits

- SAFE template based on [Y Combinator's standard post-money SAFE](https://www.ycombinator.com/documents)
- Inspired by Praful Mathur's [SAFE-CLI-Signer](https://github.com/prafulfillment/SAFE-CLI-Signer)
- Protocol based on Rubinstein (1982) and Fatima, Kraus, Wooldridge (2014)

## Related

- [APOA](https://github.com/agenticpoa/apoa) -- Agentic Power of Attorney spec + SDKs
- [sshsign](https://github.com/agenticpoa/sshsign) -- SSH signing infrastructure

## License

MIT
