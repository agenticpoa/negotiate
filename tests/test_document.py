"""Tests for the document generator and SAFE template."""

import os
import tempfile

import pytest

from documents.generator import generate_document
from documents.templates.safe import SAFETemplate


VALID_TERMS = {
    "valuation_cap": 10_000_000,
    "discount_rate": 0.20,
    "pro_rata": True,
    "mfn": False,
    "date": "2026-04-01",
    "investment_amount": 500_000.0,
}

VALID_PARTIES = {
    "founder": {
        "company": "Acme Corp",
        "name": "Jane Doe",
        "title": "CEO",
    },
    "investor": {
        "name": "Angel Ventures",
    },
}


class TestSAFETemplate:
    def test_validate_terms_passes(self):
        template = SAFETemplate(VALID_TERMS, VALID_PARTIES)
        valid, reason = template.validate_terms()
        assert valid
        assert reason == ""

    def test_missing_required_field_fails(self):
        terms = {k: v for k, v in VALID_TERMS.items() if k != "valuation_cap"}
        template = SAFETemplate(terms, VALID_PARTIES)
        valid, reason = template.validate_terms()
        assert not valid
        assert "valuation_cap" in reason

    def test_missing_party_fails(self):
        parties = {"founder": VALID_PARTIES["founder"]}
        template = SAFETemplate(VALID_TERMS, parties)
        valid, reason = template.validate_terms()
        assert not valid
        assert "investor" in reason

    def test_missing_party_field_fails(self):
        parties = {
            "founder": {"company": "Acme Corp"},  # missing name and title
            "investor": VALID_PARTIES["investor"],
        }
        template = SAFETemplate(VALID_TERMS, parties)
        valid, reason = template.validate_terms()
        assert not valid

    def test_generates_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            template = SAFETemplate(VALID_TERMS, VALID_PARTIES)
            doc_hash = template.generate_pdf(path)
            assert os.path.exists(path)
            assert os.path.getsize(path) > 0
            assert len(doc_hash) == 64  # SHA-256 hex
        finally:
            os.unlink(path)

    def test_pdf_is_deterministic(self):
        """Same inputs must produce the same hash."""
        hashes = []
        paths = []
        for _ in range(2):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                path = f.name
            paths.append(path)
            template = SAFETemplate(VALID_TERMS, VALID_PARTIES)
            hashes.append(template.generate_pdf(path))
        try:
            assert hashes[0] == hashes[1]
        finally:
            for p in paths:
                os.unlink(p)

    def test_pdf_readable(self):
        """Generated PDF starts with the PDF magic bytes."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            SAFETemplate(VALID_TERMS, VALID_PARTIES).generate_pdf(path)
            with open(path, "rb") as f:
                header = f.read(5)
            assert header == b"%PDF-"
        finally:
            os.unlink(path)


class TestDocumentGenerator:
    def test_generate_safe(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            path = f.name
        try:
            doc_hash = generate_document("safe-agreement", VALID_TERMS, VALID_PARTIES, path)
            assert len(doc_hash) == 64
            assert os.path.exists(path)
        finally:
            os.unlink(path)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown document type"):
            generate_document("unknown-doc", {}, {}, "/tmp/test.pdf")

    def test_invalid_terms_raises(self):
        with pytest.raises(ValueError, match="Invalid terms"):
            generate_document("safe-agreement", {}, VALID_PARTIES, "/tmp/test.pdf")
