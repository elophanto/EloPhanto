"""Tests for core/pii_guard.py — PII detection and redaction."""

from __future__ import annotations

from core.pii_guard import PIIType, redact_pii, redact_pii_in_dict, scan_for_pii


class TestScanForPII:
    def test_ssn_detection(self) -> None:
        """Should detect US SSN patterns."""
        matches = scan_for_pii("My SSN is 123-45-6789 and that's private")
        assert len(matches) >= 1
        assert any(m.pii_type == PIIType.SSN for m in matches)

    def test_credit_card_luhn_valid(self) -> None:
        """Should detect valid credit card numbers (Luhn check)."""
        # Visa test number: 4111111111111111
        matches = scan_for_pii("Card number: 4111111111111111")
        cc_matches = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc_matches) >= 1

    def test_credit_card_luhn_invalid(self) -> None:
        """Should NOT detect numbers that fail Luhn check."""
        # 1234567890123456 fails Luhn
        matches = scan_for_pii("Number: 1234567890123456")
        cc_matches = [m for m in matches if m.pii_type == PIIType.CREDIT_CARD]
        assert len(cc_matches) == 0

    def test_phone_detection(self) -> None:
        """Should detect US phone number patterns."""
        matches = scan_for_pii("Call me at (555) 123-4567")
        phone_matches = [m for m in matches if m.pii_type == PIIType.PHONE]
        assert len(phone_matches) >= 1

    def test_email_password_combo(self) -> None:
        """Should detect email + password combos."""
        text = "email: user@example.com password: secret123"
        matches = scan_for_pii(text)
        ep_matches = [m for m in matches if m.pii_type == PIIType.EMAIL_PASSWORD]
        assert len(ep_matches) >= 1

    def test_api_key_detection(self) -> None:
        """Should detect API key patterns."""
        matches = scan_for_pii("Use sk-abcdefghijklmnopqrstuvwxyz for the API")
        key_matches = [m for m in matches if m.pii_type == PIIType.API_KEY]
        assert len(key_matches) >= 1

    def test_github_token_detection(self) -> None:
        """Should detect GitHub token patterns."""
        token = "ghp_" + "a" * 36
        matches = scan_for_pii(f"Token: {token}")
        key_matches = [m for m in matches if m.pii_type == PIIType.API_KEY]
        assert len(key_matches) >= 1

    def test_bank_account_detection(self) -> None:
        """Should detect bank account number patterns."""
        matches = scan_for_pii("Account number: 123456789012")
        bank_matches = [m for m in matches if m.pii_type == PIIType.BANK_ACCOUNT]
        assert len(bank_matches) >= 1

    def test_clean_text_no_matches(self) -> None:
        """Clean text should produce no matches."""
        matches = scan_for_pii("Hello, this is a normal message about weather.")
        assert len(matches) == 0

    def test_matches_sorted_by_position(self) -> None:
        """Matches should be sorted by start position."""
        text = "SSN: 123-45-6789 and phone (555) 123-4567"
        matches = scan_for_pii(text)
        if len(matches) > 1:
            for i in range(len(matches) - 1):
                assert matches[i].start <= matches[i + 1].start


class TestRedactPII:
    def test_ssn_redacted(self) -> None:
        """SSN should be replaced with redaction marker."""
        text = "My SSN is 123-45-6789"
        result = redact_pii(text)
        assert "123-45-6789" not in result
        assert "[PII:SSN detected" in result

    def test_clean_text_unchanged(self) -> None:
        """Text without PII should pass through unchanged."""
        text = "Hello, this is fine."
        assert redact_pii(text) == text

    def test_custom_matches(self) -> None:
        """Should use provided matches instead of scanning."""
        from core.pii_guard import PIIMatch

        text = "Some text here"
        matches = [PIIMatch(pii_type=PIIType.SSN, start=5, end=9)]
        result = redact_pii(text, matches)
        assert "text" not in result
        assert "[PII:SSN detected" in result

    def test_multiple_redactions(self) -> None:
        """Multiple PII items should all be redacted."""
        text = "SSN: 123-45-6789, phone (555) 123-4567"
        result = redact_pii(text)
        assert "123-45-6789" not in result


class TestPIIMatch:
    def test_redacted_property(self) -> None:
        """PIIMatch.redacted should return proper marker."""
        from core.pii_guard import PIIMatch

        m = PIIMatch(pii_type=PIIType.CREDIT_CARD, start=0, end=16)
        assert "CREDIT_CARD" in m.redacted
        assert "redacted" in m.redacted


class TestRedactPIIInDict:
    def test_flat_dict(self) -> None:
        """PII in flat dict string values should be redacted."""
        d = {"output": "SSN: 123-45-6789", "status": "ok"}
        result = redact_pii_in_dict(d)
        assert "123-45-6789" not in result["output"]
        assert result["status"] == "ok"

    def test_nested_dict(self) -> None:
        """PII in nested dict values should be redacted."""
        d = {"data": {"info": "Card: 4111111111111111"}}
        result = redact_pii_in_dict(d)
        assert "4111111111111111" not in str(result)

    def test_list_values(self) -> None:
        """PII in list items should be redacted."""
        d = {"items": ["SSN: 123-45-6789", "normal text here"]}
        result = redact_pii_in_dict(d)
        assert "123-45-6789" not in result["items"][0]
        assert result["items"][1] == "normal text here"

    def test_short_strings_skipped(self) -> None:
        """Strings <= 10 chars should not be scanned."""
        d = {"id": "abc123"}
        result = redact_pii_in_dict(d)
        assert result["id"] == "abc123"

    def test_internal_keys_skipped(self) -> None:
        """Keys starting with _ should not be scanned."""
        d = {"_injection_warning": "SSN: 123-45-6789"}
        result = redact_pii_in_dict(d)
        assert result["_injection_warning"] == "SSN: 123-45-6789"

    def test_max_depth_respected(self) -> None:
        """Beyond max_depth, values should pass through unchanged."""
        deep = {"a": {"b": {"c": {"d": {"e": "SSN: 123-45-6789"}}}}}
        result = redact_pii_in_dict(deep, max_depth=2)
        # At depth 2 the inner dicts stop being recursed
        assert "123-45-6789" in str(result)

    def test_non_dict_passthrough(self) -> None:
        """Non-dict/list/str values should pass through unchanged."""
        assert redact_pii_in_dict(42) == 42
        assert redact_pii_in_dict(None) is None
        assert redact_pii_in_dict(3.14) == 3.14
