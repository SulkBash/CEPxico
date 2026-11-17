"""Data extracted from a payment receipt."""

from __future__ import annotations

from dataclasses import dataclass, field

from cepxico.banks import clabe_is_valid

# Label shown to users for each field.
FIELD_LABELS = {
    "payment_date": "fecha de pago",
    "tracking_key": "clave de rastreo",
    "sender_bank": "banco emisor",
    "receiver_bank": "banco receptor",
    "beneficiary_account": "cuenta beneficiaria",
    "amount": "monto",
}

# Fields the receipt itself must provide, in reporting order. The sending bank isn't
# here: it's identified later against Banxico's catalog (see identify.py).
REQUIRED_FIELDS = ("payment_date", "tracking_key", "receiver_bank", "beneficiary_account", "amount")


@dataclass
class PaymentData:
    """Fields read from one SPEI receipt. `None` means "not found on the receipt"."""

    source_file: str
    payment_date: str | None = None  # dd-mm-yyyy, as Banxico expects
    tracking_key: str | None = None  # clave de rastreo
    sender_bank: str | None = None  # text next to a "Banco emisor/origen" label, if any
    receiver_bank: str | None = None  # text next to a "Banco destino/receptor" label, if any
    beneficiary_account: str | None = None  # CLABE (18), debit card (16) or phone (10)
    amount: str | None = None  # e.g. "1234.50"
    error_reason: str = ""
    text: str = field(default="", repr=False, compare=False)  # full receipt text

    def missing_fields(self) -> list[str]:
        """Required fields still missing. The receiving bank isn't needed when the
        account is a valid CLABE, because its first 3 digits identify the bank."""
        missing = [name for name in REQUIRED_FIELDS if getattr(self, name) is None]
        if "receiver_bank" in missing and clabe_is_valid(self.beneficiary_account):
            missing.remove("receiver_bank")
        return missing
