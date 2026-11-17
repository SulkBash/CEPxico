"""
Deciding which banks a transfer went between.

Receiving bank: the CLABE's first 3 digits if it's a valid CLABE, else the receipt's
"Banco destino/receptor" field.

Sending bank, first clue that works wins:
  1. the receipt's "Banco emisor/origen" field
  2. a clave de rastreo prefix known to belong to one bank
  3. wording that only appears on one bank's own receipts
  4. the first bank named anywhere on the receipt
Steps 2-4 never pick the receiving bank: a CEP is always between two different banks,
and receipts name the receiving bank too. Step 1 is the receipt's own statement, so it's
returned even if it names the receiving bank; pipeline.py rejects that transfer instead
of guessing another sender.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from cepxico.banks import Bank, BankDirectory
from cepxico.models import PaymentData


class BankSource(StrEnum):
    CLABE = "CLABE prefix"
    LABEL = "receipt field"
    TRACKING_KEY = "clave de rastreo prefix"
    SIGNATURE = "bank-specific wording"
    TEXT = "bank named on receipt"


@dataclass(frozen=True)
class BankMatch:
    bank: Bank
    source: BankSource

    def __str__(self) -> str:
        return f"{self.bank.name} ({self.source.value})"


def identify_receiver(payment: PaymentData, directory: BankDirectory) -> BankMatch | None:
    if bank := directory.catalog.by_clabe(payment.beneficiary_account):
        return BankMatch(bank, BankSource.CLABE)
    if bank := directory.resolve(payment.receiver_bank):
        return BankMatch(bank, BankSource.LABEL)
    return None


def identify_sender(payment: PaymentData, directory: BankDirectory, *, receiver: Bank) -> BankMatch | None:
    if bank := directory.resolve(payment.sender_bank):
        return BankMatch(bank, BankSource.LABEL)

    def other_than_receiver(banks: list[Bank]) -> Bank | None:
        return next((b for b in banks if b != receiver), None)

    if (bank := directory.by_tracking_key(payment.tracking_key)) and bank != receiver:
        return BankMatch(bank, BankSource.TRACKING_KEY)
    if bank := other_than_receiver(directory.by_signature(payment.text)):
        return BankMatch(bank, BankSource.SIGNATURE)
    if bank := other_than_receiver(directory.banks_in_text(payment.text)):
        return BankMatch(bank, BankSource.TEXT)
    return None
