"""Smoke tests for beancount-lalitm importers.

These tests verify basic functionality:
- Importers can be instantiated
- File identification works correctly
- Basic extraction produces valid beancount directives
"""
import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from beancount.core.data import Transaction, Balance, Commodity

# Fixtures path
FIXTURES = Path(__file__).parent / 'fixtures'


class MockFileMemo:
    """Mock beangulp FileMemo for testing."""

    def __init__(self, path: Path):
        self.name = str(path)
        self._path = path

    def head(self, num_bytes: int = 8192) -> str:
        if not self._path.exists():
            return ''
        return self._path.read_text()[:num_bytes]

    def contents(self) -> str:
        return self._path.read_text()


class TestAccountOracle:
    """Tests for AccountOracle helper class."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle is not None

    def test_cash_account(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle.cash_account() == 'Assets:Lalit:US:IB:Brokerage:Cash'

    def test_asset_account(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle.asset_account('AAPL') == 'Assets:Lalit:US:IB:Brokerage:AAPL'

    def test_distribution_account_with_commodity_metadata(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount.core.data import new_metadata

        commodity = Commodity(
            meta={**new_metadata('test', 1), 'distribution_type': 'Dividends'},
            date=datetime.date(2024, 1, 1),
            currency='AAPL',
        )
        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[commodity],
        )
        assert oracle.distribution_account('AAPL') == \
            'Revenues:Lalit:US:IB:Brokerage:AAPL:Dividends'

    def test_transfers_account_raises_when_not_configured(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        with pytest.raises(ValueError, match='transfers_account not configured'):
            oracle.transfers_account()

    def test_transfers_account_when_configured(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        assert oracle.transfers_account() == 'Assets:Transfers'

    def test_commission_account(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle.commission_account('AAPL') == \
            'Expenses:Lalit:US:IB:Brokerage:AAPL:Commissions'

    def test_capital_gains_account(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle.capital_gains_account('AAPL') == \
            'Revenues:Lalit:US:IB:Brokerage:AAPL:Capital-Gains'

    def test_withholding_taxes_account(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
        )
        assert oracle.withholding_taxes_account('AAPL') == \
            'Expenses:Lalit:US:IB:Brokerage:AAPL:Withholding-Tax'


class TestHsbcUkCcImporter:
    """Tests for HSBC UK Credit Card importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.hsbc_uk_cc import HsbcUkCcImporter

        importer = HsbcUkCcImporter(account='Liabilities:HSBC:CreditCard')
        assert importer.account == 'Liabilities:HSBC:CreditCard'

    def test_identify_json_file(self):
        from beancount_lalitm.importers.hsbc_uk_cc import HsbcUkCcImporter

        importer = HsbcUkCcImporter(account='Liabilities:HSBC:CreditCard')
        file = MockFileMemo(FIXTURES / 'hsbc_uk_cc.json')
        assert importer.identify(file) is True

    def test_identify_non_json_file(self):
        from beancount_lalitm.importers.hsbc_uk_cc import HsbcUkCcImporter

        importer = HsbcUkCcImporter(account='Liabilities:HSBC:CreditCard')
        file = MockFileMemo(FIXTURES / 'hsbc_uk.txt')
        assert importer.identify(file) is False


class TestHsbcImporter:
    """Tests for HSBC UK current account importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.hsbc import HsbcImporter

        importer = HsbcImporter(account='Assets:HSBC:Current')
        assert importer.account == 'Assets:HSBC:Current'

    def test_identify_txt_file(self):
        from beancount_lalitm.importers.hsbc import HsbcImporter

        importer = HsbcImporter(account='Assets:HSBC:Current')
        file = MockFileMemo(FIXTURES / 'hsbc_uk.txt')
        assert importer.identify(file) is True

    def test_identify_non_txt_file(self):
        from beancount_lalitm.importers.hsbc import HsbcImporter

        importer = HsbcImporter(account='Assets:HSBC:Current')
        file = MockFileMemo(FIXTURES / 'hsbc_uk_cc.json')
        assert importer.identify(file) is False


class TestIbImporter:
    """Tests for Interactive Brokers importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ib import IbImporter

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        importer = IbImporter(account_currency='USD', account_oracle=oracle)
        assert importer.account_currency == 'USD'

    def test_identify_flex_query_xml(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ib import IbImporter

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        importer = IbImporter(account_currency='USD', account_oracle=oracle)
        file = MockFileMemo(FIXTURES / 'ib_flex_query.xml')
        assert importer.identify(file) is True

    def test_identify_non_xml_file(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ib import IbImporter

        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        importer = IbImporter(account_currency='USD', account_oracle=oracle)
        file = MockFileMemo(FIXTURES / 'hsbc_uk.txt')
        assert importer.identify(file) is False

    def test_extract_transactions(self):
        from beancount.core.data import new_metadata
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ib import IbImporter

        # Create commodity for AAPL with distribution type
        commodity = Commodity(
            meta={**new_metadata('test', 1), 'distribution_type': 'Dividends'},
            date=datetime.date(2024, 1, 1),
            currency='AAPL',
        )
        oracle = AccountOracle(
            account='Lalit:US:IB:Brokerage',
            entries=[commodity],
            transfers_account='Assets:Transfers',
        )
        importer = IbImporter(account_currency='USD', account_oracle=oracle)
        file = MockFileMemo(FIXTURES / 'ib_flex_query.xml')

        transactions = importer.extract(file, existing_entries=None)

        # Should have: 1 deposit, 1 dividend, 1 stock buy
        assert len(transactions) == 3

        # Check deposit
        deposit = next(t for t in transactions if 'Electronic Fund Transfer' in t.narration)
        assert deposit.postings[0].units.number == Decimal('1000.00')
        assert deposit.postings[0].units.currency == 'USD'

        # Check dividend
        dividend = next(t for t in transactions if 'Dividend' in t.narration)
        assert dividend.postings[0].units.number == Decimal('10.50')

        # Check stock buy
        buy = next(t for t in transactions if t.narration == 'BUY')
        assert buy.postings[0].units.number == Decimal('10')
        assert buy.postings[0].units.currency == 'AAPL'


class TestHsbcUsCcImporter:
    """Tests for HSBC US Credit Card importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.hsbc_us_cc import HsbcUsCcImporter

        importer = HsbcUsCcImporter(account='Liabilities:HSBC:US:CreditCard')
        assert importer.account == 'Liabilities:HSBC:US:CreditCard'


class TestHsbcUsCheckingImporter:
    """Tests for HSBC US Checking importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.hsbc_us_checking import HsbcUsCheckingImporter

        importer = HsbcUsCheckingImporter(account='Assets:HSBC:US:Checking')
        assert importer.account == 'Assets:HSBC:US:Checking'


class TestVanguardImporter:
    """Tests for Vanguard UK importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.vanguard import VanguardImporter, SheetMatcher

        oracle = AccountOracle(
            account='Lalit:UK:Vanguard:ISA',
            entries=[],
        )
        matcher = SheetMatcher(
            sheet_name='ISA',
            account_oracle=oracle,
            investment_map={'Vanguard FTSE Global All Cap': 'VWRP'},
        )
        importer = VanguardImporter(matchers=[matcher])
        assert importer is not None
        assert len(importer.matches) == 1


class TestIgImporter:
    """Tests for IG Trading importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ig import IgImporter

        oracle = AccountOracle(
            account='Lalit:UK:IG:Trading',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        importer = IgImporter(
            filepath_filter=r'.*ig.*\.txt',
            account_oracle=oracle,
            isin_lookup={'GB00B3X7QG63': 'VWRL'},
            base_dir='/tmp',
        )
        assert importer is not None


class TestAjBellImporters:
    """Tests for AJ Bell importers."""

    def test_transactions_importer_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ajbell import AjTransactionsImporter

        oracle = AccountOracle(
            account='Lalit:UK:AJBell:ISA',
            entries=[],
        )
        importer = AjTransactionsImporter(
            account_id='ABBPRVI',
            account_oracle=oracle,
            sedol_symbol_map={'B3X7QG6': 'VWRL'},
        )
        assert importer is not None

    def test_cash_importer_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.ajbell import AjCashImporter

        oracle = AccountOracle(
            account='Lalit:UK:AJBell:ISA',
            entries=[],
            transfers_account='Assets:Transfers',
        )
        importer = AjCashImporter(
            filename_filter=r'.*ajbell.*\.csv',
            account_oracle=oracle,
            distribution_description_to_symbol_map={'VANGUARD FTSE': 'VWRL'},
        )
        assert importer is not None


class TestAvivaPensionImporter:
    """Tests for Aviva Pension importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.aviva import AvivaPensionImporter

        oracle = AccountOracle(
            account='Lalit:UK:Aviva:Pension',
            entries=[],
        )
        importer = AvivaPensionImporter(account_oracle=oracle)
        assert importer is not None


class TestSchwabEacImporter:
    """Tests for Schwab Equity Award Center importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.account_lookup import AccountOracle
        from beancount_lalitm.importers.schwab_eac import SchwabEacImporter

        oracle = AccountOracle(
            account='Lalit:US:Schwab:EAC',
            entries=[],
            stock_revenue_account='Revenues:Salary:Stock',
        )
        importer = SchwabEacImporter(
            account_currency='USD',
            filename_filter=r'.*schwab.*\.txt',
            account_oracle=oracle,
            base_dir='/tmp',
            stock_symbol='GOOG',
        )
        assert importer is not None


class TestGooglePayslipImporter:
    """Tests for Google UK Payslip importer."""

    def test_instantiation(self):
        from beancount_lalitm.importers.google import GooglePayslipImporter

        importer = GooglePayslipImporter(
            gross_salary_revenue_account='Revenues:Salary:Google:Gross',
            pension_transfer_account='Assets:Pension:Google',
            peer_bonus_revenue_account='Revenues:Salary:Google:PeerBonus',
            spot_bonus_revenue_account='Revenues:Salary:Google:SpotBonus',
            annual_bonus_revenue_account='Revenues:Salary:Google:AnnualBonus',
            income_tax_account='Expenses:Tax:Income',
            ni_account='Expenses:Tax:NI',
            payslip_transfer_account='Assets:Current:HSBC',
            stock_withholding_revenue_account='Revenues:Salary:Google:StockWithholding',
            student_loan_expense_account='Expenses:StudentLoan',
            ee_gia_transfer_account='Assets:Google:EE-GIA',
            commuter_loan_transfer_account='Assets:Google:CommuterLoan',
            leave_purchase_expense_account='Expenses:LeavePurchase',
        )
        assert importer is not None
