"""Data extracted from a payment receipt."""

from __future__ import annotations

from dataclasses import dataclass

from cepxico.banks import clabe_is_valid

# Fields Banxico needs to locate a transfer, in the order they're reported,
# with the label shown to users.
FIELD_LABELS = {
    "payment_date": "fecha de pago",
    "tracking_key": "clave de rastreo",
    "sender_bank": "banco emisor",
    "receiver_bank": "banco receptor",
    "beneficiary_account": "cuenta beneficiaria",
    "amount": "monto",
}
REQUIRED_FIELDS = tuple(FIELD_LABELS)


@dataclass
class PaymentData:
    """Fields read from one SPEI receipt. `None` means "not found on the receipt"."""

    source_file: str
    payment_date: str | None = None  # dd-mm-yyyy, as Banxico expects
    tracking_key: str | None = None  # clave de rastreo
    sender_bank: str | None = None  # institución emisora, as written on the receipt
    receiver_bank: str | None = None  # institución receptora, as written on the receipt
    beneficiary_account: str | None = None  # CLABE (18), debit card (16) or phone (10)
    amount: str | None = None  # e.g. "1234.50"
    error_reason: str = ""

    def missing_fields(self) -> list[str]:
        """Required fields still missing. The receiving bank isn't needed when the
        account is a valid CLABE, because its first 3 digits identify the bank."""
        missing = [name for name in REQUIRED_FIELDS if getattr(self, name) is None]
        if "receiver_bank" in missing and clabe_is_valid(self.beneficiary_account):
            missing.remove("receiver_bank")
        return missing
