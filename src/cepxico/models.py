"""Data extracted from a payment receipt."""

from __future__ import annotations

from dataclasses import dataclass, field

from cepxico.banks import clabe_is_valid
from cepxico.i18n import tr

# Fields shown to users, in display order; field_label() gives each one's name.
FIELD_NAMES = (
    "payment_date",
    "tracking_key",
    "sender_bank",
    "receiver_bank",
    "beneficiary_account",
    "amount",
)
# Everything the user can change in a receipt's data, for listing what they changed.
FLAGS = ("pago_a_banco", "spid")  # yes/no fields
EDITABLE_FIELDS = (*FIELD_NAMES, *FLAGS)


def field_label(name: str) -> str:
    """What field `name` is called, lowercase, in the current language."""
    labels = {
        "payment_date": tr("payment date"),
        "tracking_key": tr("clave de rastreo"),
        "sender_bank": tr("sending bank"),
        "receiver_bank": tr("receiving bank"),
        "beneficiary_account": tr("beneficiary account"),
        "amount": tr("amount"),
        "pago_a_banco": tr("pago a banco"),
        "spid": tr("dollars (SPID)"),
    }
    return labels[name]


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
    # Paid to the receiving bank itself, not to one of its customers (Banxico's "Pago a
    # Banco"). `beneficiary_account` then holds the *ordering* account, as Banxico asks.
    pago_a_banco: bool = False
    amount: str | None = None  # e.g. "1234.50"
    # A dollar transfer through SPID, not SPEI: Banxico's CEP-SPID service, not checked here.
    spid: bool = False
    error_reason: str = ""
    text: str = field(default="", repr=False, compare=False)  # full receipt text
    edited_fields: tuple[str, ...] = ()  # fields the user typed in, not read from the receipt

    def missing_fields(self) -> list[str]:
        """Required fields still missing. The receiving bank isn't needed when the
        account is a valid CLABE, because its first 3 digits identify the bank (not so
        for a pago a banco, where the account is the sender's)."""
        missing = [name for name in REQUIRED_FIELDS if getattr(self, name) is None]
        if "receiver_bank" in missing and not self.pago_a_banco and clabe_is_valid(self.beneficiary_account):
            missing.remove("receiver_bank")
        return missing

    def label(self, name: str) -> str:
        """How to call field `name` for this payment."""
        if name == "beneficiary_account" and self.pago_a_banco:
            return tr("ordering account")
        return field_label(name)
