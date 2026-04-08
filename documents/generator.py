"""Document generator registry. Maps document types to template classes."""

from __future__ import annotations

from documents.templates.safe import SAFETemplate

TEMPLATES = {
    "safe-agreement": SAFETemplate,
}


def generate_document(
    doc_type: str,
    terms: dict,
    parties: dict,
    output_path: str,
) -> str:
    """
    Generate a document PDF and return its SHA-256 hash.

    Raises ValueError if the document type is unknown or terms are invalid.
    """
    template_class = TEMPLATES.get(doc_type)
    if not template_class:
        raise ValueError(f"Unknown document type: {doc_type}")

    template = template_class(terms, parties)
    valid, reason = template.validate_terms()
    if not valid:
        raise ValueError(f"Invalid terms: {reason}")

    return template.generate_pdf(output_path)


def generate_executed_document(
    doc_type: str,
    terms: dict,
    parties: dict,
    output_path: str,
    signers: list[dict] | None = None,
    doc_hash: str = "",
    negotiation_history: list[dict] | None = None,
    negotiation_id: str = "",
    elapsed_seconds: float | None = None,
    # Legacy single-signer params (backwards compatibility)
    signature_block: str = "",
    key_id: str = "",
    audit_tx_id: int | str | None = None,
    pending_id: str = "",
    signature_image_b64: str | None = None,
) -> str:
    """
    Generate an executed document PDF with the negotiation audit trail
    and signatures from all parties appended.
    Returns the new file hash.
    """
    template_class = TEMPLATES.get(doc_type)
    if not template_class:
        raise ValueError(f"Unknown document type: {doc_type}")

    template = template_class(terms, parties)
    valid, reason = template.validate_terms()
    if not valid:
        raise ValueError(f"Invalid terms: {reason}")

    # Convert legacy single-signer to list format
    if signers is None and signature_block:
        signers = [{
            "role": "signer",
            "key_id": key_id,
            "signature": signature_block,
            "signature_image": signature_image_b64,
            "audit_tx_id": audit_tx_id,
            "pending_id": pending_id,
        }]

    return template.append_execution_page(
        pdf_path=output_path,
        signers=signers or [],
        doc_hash=doc_hash,
        negotiation_history=negotiation_history,
        negotiation_id=negotiation_id,
        elapsed_seconds=elapsed_seconds,
    )
