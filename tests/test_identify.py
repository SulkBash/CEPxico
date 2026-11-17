from cepxico.banks import Bank
from cepxico.extraction.parser import parse_payment
from cepxico.identify import BankSource, identify_receiver, identify_sender
from cepxico.models import PaymentData
from tests.conftest import with_check_digit
from tests.test_parser import BANORTE_RECEIPT, BBVA_RECEIPT, SANTANDER_RECEIPT

BBVA = Bank("40012", "BBVA MEXICO")
BANORTE = Bank("40072", "BANORTE")
SANTANDER = Bank("40014", "SANTANDER")


def payment(text: str = "", **fields) -> PaymentData:
    return PaymentData(source_file="r.pdf", text=text, **fields)


class TestReceiver:
    def test_clabe_wins_over_label(self, directory):
        p = payment(beneficiary_account=with_check_digit("01218000123456789"), receiver_bank="BANORTE")
        match = identify_receiver(p, directory)
        assert match.bank == BBVA and match.source is BankSource.CLABE

    def test_label_when_account_is_not_a_clabe(self, directory):
        match = identify_receiver(
            payment(beneficiary_account="5512345678", receiver_bank="Banorte"), directory
        )
        assert match.bank == BANORTE and match.source is BankSource.LABEL

    def test_unknown(self, directory):
        assert identify_receiver(payment(receiver_bank="Banco Inexistente"), directory) is None


class TestSender:
    def test_label_first(self, directory):
        p = payment("BBVA ... Banco emisor: Santander", sender_bank="Santander")
        match = identify_sender(p, directory, receiver=BBVA)
        assert match.bank == SANTANDER and match.source is BankSource.LABEL

    def test_tracking_key_prefix(self, directory):
        p = payment("Transferencia SPEI", tracking_key="BNET01002611050012345678")
        match = identify_sender(p, directory, receiver=BANORTE)
        assert match.bank == BBVA and match.source is BankSource.TRACKING_KEY

    def test_signature(self, directory):
        p = payment("BANCO MERCANTIL DEL NORTE S.A.\nBanco destino: STP")
        match = identify_sender(p, directory, receiver=Bank("90646", "STP"))
        assert match.bank == BANORTE and match.source is BankSource.SIGNATURE

    def test_receiver_is_never_the_sender(self, directory):
        """The v1 bug: a transfer *to* BBVA was reported as *from* BBVA."""
        p = payment("BANORTE\nBanco Destino: BBVA MEXICO", receiver_bank="BBVA MEXICO")
        match = identify_sender(p, directory, receiver=BBVA)
        assert match.bank == BANORTE and match.source is BankSource.TEXT

    def test_signature_of_the_receiver_is_ignored(self, directory):
        # Banorte's legal name printed as the *destination* must not make Banorte the sender.
        p = payment("Santander\nBanco destino: Banco Mercantil del Norte")
        match = identify_sender(p, directory, receiver=BANORTE)
        assert match.bank == SANTANDER

    def test_nothing_to_go_on(self, directory):
        p = payment("Banco Destino: BBVA MEXICO", receiver_bank="BBVA MEXICO")
        assert identify_sender(p, directory, receiver=BBVA) is None


class TestSampleReceipts:
    """Parsing + identification together, on the sample receipts from test_parser.py."""

    def identify(self, directory, text):
        p = parse_payment(text)
        receiver = identify_receiver(p, directory)
        sender = identify_sender(p, directory, receiver=receiver.bank if receiver else None)
        return sender, receiver

    def test_santander_to_bbva(self, directory):
        sender, receiver = self.identify(directory, SANTANDER_RECEIPT)
        assert sender.bank == SANTANDER and sender.source is BankSource.SIGNATURE
        assert receiver.bank == BBVA

    def test_banorte_to_stp(self, directory):
        sender, receiver = self.identify(directory, BANORTE_RECEIPT)
        assert sender.bank == BANORTE and sender.source is BankSource.SIGNATURE
        assert receiver.bank == Bank("90646", "STP")

    def test_bbva_from_tracking_key(self, directory):
        sender, _ = self.identify(directory, BBVA_RECEIPT)
        assert sender.bank == BBVA and sender.source is BankSource.TRACKING_KEY
