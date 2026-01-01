"""Importer for Interactive Brokers Flex Query reports.

Interactive Brokers (IB) is a brokerage platform. This importer parses
XML Flex Query reports containing:
- Cash transactions (deposits, withdrawals, dividends, interest, fees)
- Trade executions (stocks, forex)
- Corporate actions (splits, mergers)

Flex Query Setup:
  In IB Account Management, create a Flex Query with these sections enabled:
  - Cash Transactions
  - Corporate Actions
  - Financial Instrument Information
  - Statement of Funds
  - Trades
"""
from beancount.core.data import Amount, Entries, Posting, Transaction, new_metadata
from beangulp import importer
from beangulp.cache import _FileMemo
import collections
import datetime
from decimal import Decimal
import xmltodict

from beancount_lalitm.importers.account_lookup import AccountOracle


def process_cash_transaction(
    c: dict,
    first_account: str,
    second_account: str,
    tags: set[str],
) -> Transaction:
  date = datetime.datetime.strptime(c['@reportDate'], '%d-%b-%y').date()
  amount = Amount(Decimal(c['@amount']), c['@currency'])
  first = Posting(
      account=first_account,
      units=amount,
      cost=None,
      price=None,
      flag=None,
      meta=collections.OrderedDict(ib_transaction_id=c['@transactionID']),
  )
  second = Posting(
      account=second_account,
      units=-amount,
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )
  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration=c['@description'],
      tags=tags,
      links=set(),
      postings=[first, second],
  )


def add_commissions_to_postings(
    t: dict,
    symbol: str,
    account_oracle: AccountOracle,
) -> list[Posting]:
  commission = Amount(Decimal(t['@ibCommission']), t['@ibCommissionCurrency'])
  if not commission.number or commission.number == 0:
    return []
  commission_account_posting = Posting(
      account=account_oracle.cash_account(),
      units=commission,
      cost=None,
      price=None,
      flag=None,
      meta=collections.OrderedDict(),
  )
  commission_cash_posting = Posting(
      account=account_oracle.commission_account(symbol),
      units=-commission,
      cost=None,
      price=None,
      flag=None,
      meta=collections.OrderedDict(),
  )
  return [
      commission_account_posting,
      commission_cash_posting,
  ]


def process_forex_transaction(
    t: dict,
    account_oracle: AccountOracle,
) -> Transaction:
  assert t['@buySell'] == 'BUY' or t['@buySell'] == 'SELL'

  date = datetime.datetime.strptime(t['@tradeDate'], '%d-%b-%y').date()
  (sa, sb) = t['@symbol'].split('.')

  first_posting = Posting(
      account=account_oracle.cash_account(),
      units=Amount(Decimal(t['@quantity']), sa),
      cost=None,
      price=Amount(Decimal(t['@tradePrice']), sb),
      flag=None,
      meta=collections.OrderedDict(ib_transaction_id=t['@transactionID']),
  )
  second_posting = Posting(
      account=account_oracle.cash_account(),
      units=Amount(Decimal(t['@proceeds']), sb),
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )

  postings = [first_posting, second_posting]
  postings.extend(add_commissions_to_postings(t, sa, account_oracle))
  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration=t['@buySell'],
      tags=set(),
      links=set(),
      postings=postings,
  )


def process_stk_transaction(
    t: dict[str, str],
    account_oracle: AccountOracle,
) -> Transaction:
  assert t['@buySell'] == 'BUY' or t['@buySell'] == 'SELL'
  date = datetime.datetime.strptime(t['@tradeDate'], '%d-%b-%y').date()

  symbol = t['@symbol'].replace(' ', '-')
  currency = t['@currency']
  price = Decimal(t['@tradePrice'])

  stock_account = account_oracle.asset_account(symbol)
  cash_account = account_oracle.cash_account()

  first_posting = Posting(
      account=stock_account,
      units=Amount(Decimal(t['@quantity']), symbol),
      cost=None,
      price=Amount(price, currency),
      flag=None,
      meta=collections.OrderedDict(ib_transaction_id=t['@transactionID']),
  )
  second_posting = Posting(
      account=cash_account,
      units=Amount(Decimal(t['@proceeds']), currency),
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )

  postings = [first_posting, second_posting]
  postings.extend(add_commissions_to_postings(t, symbol, account_oracle))
  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration=t['@buySell'],
      tags=set(),
      links=set(),
      postings=postings,
  )


def process_stk_corp_action(
    t: dict[str, str],
    account_oracle: AccountOracle,
) -> Transaction:
  date = datetime.datetime.strptime(t['@reportDate'], '%d-%b-%y').date()

  symbol = t['@symbol'].replace(' ', '-')
  currency = t['@currency']

  amount = Decimal(t['@amount'])
  proceeds = Decimal(t['@proceeds'])
  quantity = Decimal(t['@quantity'])
  price = amount / quantity
  assert amount == -proceeds

  stock_account = account_oracle.asset_account(symbol)
  cash_account = account_oracle.cash_account()

  first_posting = Posting(
      account=stock_account,
      units=Amount(quantity, symbol),
      cost=None,
      price=Amount(price, currency),
      flag=None,
      meta=collections.OrderedDict(ib_transaction_id=t['@transactionID']),
  )
  second_posting = Posting(
      account=cash_account,
      units=Amount(proceeds, currency),
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )
  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration=t['@description'],
      tags=set(),
      links=set(),
      postings=[first_posting, second_posting],
  )


class IbImporter(importer.ImporterProtocol):
  """Importer for Interactive Brokers Flex Query XML reports.

  Supports deduplication against existing entries using IB transaction IDs
  stored in posting metadata.

  Args:
    account_currency: The base currency of the account (e.g., 'USD').
    account_oracle: AccountOracle for generating account names.
  """

  def __init__(
      self,
      account_currency: str,
      account_oracle: AccountOracle,
  ):
    self.account_currency = account_currency
    self.account_oracle = account_oracle

  def identify(self, file: _FileMemo):
    return file.name.endswith('.xml') and 'FlexQueryResponse' in file.head()

  def extract(self,
              file: _FileMemo,
              existing_entries: Entries | None = None) -> list[Transaction]:
    seen_txn_ids = set()
    for entry in existing_entries or []:
      if not isinstance(entry, Transaction):
        continue
      for posting in entry.postings:
        tid = posting.meta.get('ib_transaction_id')
        if not tid:
          continue
        seen_txn_ids.add(tid)

    root: dict = xmltodict.parse(file.contents())
    stmt: dict = root['FlexQueryResponse']['FlexStatements']['FlexStatement']

    transactions: list[Transaction] = []

    cash_transactions: list[dict] | dict = stmt['CashTransactions']
    if cash_transactions:
      raw_cts = cash_transactions['CashTransaction']
      cs = raw_cts if type(raw_cts) is list else [raw_cts]
      for c in cs:
        txn_id: str = c['@transactionID']
        txn_type: str = c['@type']

        if txn_id in seen_txn_ids:
          continue

        symbol: str = c['@symbol'].replace(' ', '-')
        account = None
        if txn_type == 'Deposits/Withdrawals':
          account = self.account_oracle.transfers_account()
        elif txn_type == 'Dividends' or txn_type == 'Payment In Lieu Of Dividends':
          account = self.account_oracle.distribution_account(symbol)
        elif txn_type == 'Other Fees':
          account = self.account_oracle.account_fees_account()
        elif txn_type == 'Withholding Tax':
          account = self.account_oracle.withholding_taxes_account(symbol)
        elif txn_type == 'Broker Interest Received':
          account = self.account_oracle.account_interest_account()
        elif txn_type == 'Broker Interest Paid':
          account = self.account_oracle.account_fees_account()
        else:
          raise Exception(f'Unknown cash transaction type {txn_type}')

        cash_transaction = process_cash_transaction(
            c,
            self.account_oracle.cash_account(),
            account,
            set(),
        )
        transactions.append(cash_transaction)

    trades = stmt['Trades']
    if trades:
      raw_ts =  trades['Trade']
      ts = raw_ts if type(raw_ts) is list else [raw_ts]
      for t in ts:
        txn_id = t['@transactionID']
        asset_cat = t['@assetCategory']

        if txn_id in seen_txn_ids:
          continue

        if asset_cat == 'CASH':
          txn = process_forex_transaction(t, self.account_oracle)
        elif asset_cat == 'STK':
          txn = process_stk_transaction(t, self.account_oracle)
        else:
          raise Exception(f'Unknown trade type {asset_cat}')
        transactions.append(txn)

    corps = stmt['CorporateActions']
    if corps:
      raw_cs = corps['CorporateAction']
      cs = raw_cs if type(raw_cs) is list else [raw_cs]
      for c in cs:
        txn_id = c['@transactionID']
        asset_cat = c['@assetCategory']

        if txn_id in seen_txn_ids:
          continue

        if asset_cat == 'STK':
          txn = process_stk_corp_action(c, self.account_oracle)
        else:
          raise Exception(f'Unknown trade type {asset_cat}')
        transactions.append(txn)
    return transactions
