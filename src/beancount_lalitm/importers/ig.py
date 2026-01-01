"""Importer for IG Trading platform statements.

IG is a UK trading platform offering ISAs and GIAs. This importer parses
text-converted PDF statements containing:
- Cash transactions (deposits, withdrawals, dividends, interest)
- Stock trades (buys, sells with commission)
- Balance assertions
"""
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
import io
import math
import os
from pathlib import Path
import re
import sys
from typing import override

from beancount import Amount
from beancount import Directive
from beancount import Directives
from beancount import new_metadata
from beancount import Posting
from beancount.core.data import Balance
from beancount.core.data import Entries
from beancount.core.data import Transaction
from beangulp import importer
import pandas as pd

from beancount_lalitm.importers.account_lookup import AccountOracle


def find(lines: list[str], pattern: str) -> int:
  return next(i for i, line in enumerate(lines) if pattern in line)


def process_cash_transaction(
    c: dict,
    first_account: str,
    second_account: str,
    tags: set[str],
) -> Transaction:
  raw = str(c['Amount'])
  amount = Amount(
      Decimal(raw.replace('£', '').replace('$', '').replace(',', '')),
      c['Account Currency'],
  )
  first = Posting(
      account=first_account,
      units=amount,
      cost=None,
      price=None,
      flag=None,
      meta=None,
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
      date=c['Date'],
      flag='*',
      payee=None,
      narration=c['Details'],
      tags=frozenset(tags),
      links=frozenset(),
      postings=[first, second],
  )


def process_investment_transaction(
    t: dict,
    account_oracle: AccountOracle,
    isin_lookup: dict[str, str],
) -> Transaction:
  date = t['Date']
  symbol = isin_lookup[t['Details']] if not t['ISIN'] or isinstance(
      t['ISIN'], float) else isin_lookup[t['ISIN']]

  raw_units = str(t['Number'])
  raw_price = str(t['Price'])
  raw_value = str(t['Amount'])
  raw_commission = str(t['Charges'])

  units = Decimal(raw_units.replace(',', '')).copy_abs()
  price = Decimal(raw_price.replace(',', '')).copy_abs()
  value = Decimal(raw_value.replace(',', '')).copy_abs()
  commission = Decimal(raw_commission.replace(',', '')).copy_abs()
  corrected_commission = Decimal('0') if commission.is_nan() else commission

  if t['Currency'] == t['Account Currency']:
    symbol_price = (value + (-corrected_commission if t['Type'] == 'Bought' else
                             corrected_commission)) / units
    rate_price = None
  else:
    symbol_price = price
    rate_price = Amount(
        units * price / (value + (-corrected_commission if t['Type'] == 'Bought'
                                  else corrected_commission)), t['Currency'])

  postings = [
      Posting(
          account=account_oracle.asset_account(symbol),
          units=Amount(units if t['Type'] == 'Bought' else -units, symbol),
          cost=None,
          price=Amount(symbol_price, t['Currency']),
          flag=None,
          meta=None,
      ),
      Posting(
          account=account_oracle.cash_account(),
          units=Amount(-value if t['Type'] == 'Bought' else value,
                       t['Account Currency']),
          cost=None,
          price=rate_price,
          flag=None,
          meta=None,
      ),
  ]
  if not corrected_commission.is_zero():
    postings += [
        Posting(
            account=account_oracle.commission_account(symbol),
            units=Amount(commission, 'GBP'),
            cost=None,
            price=rate_price,
            flag=None,
            meta=None,
        )
    ]

  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration='BUY' if t['Type'] == 'Bought' else 'SELL',
      tags=frozenset(),
      links=frozenset(),
      postings=postings,
  )


def account_activity_to_table(currency: str, lines: list[str]) -> pd.DataFrame:
  starts = [i for i, l in enumerate(lines) if 'Dealing' in l and 'Credit' in l]
  dfs: list[pd.DataFrame] = []
  for s in starts:
    try:
      end = find(lines[s:], ' Page ')
    except StopIteration:
      end = find(lines[s:], ' Balance  ')

    if lines[s + 1].find('Trd') != -1:
      isin_idx = lines[s + 1].find('ISIN')
      code_idx = lines[s + 1].find('Deal')
      order_type_idx = lines[s + 1].find('Type')
      type_idx = lines[s + 1].find('Transaction')
      currency_idx = lines[s + 1].find('Trd')
      price_idx = lines[s + 1].find('Dealing')
      conv_idx = lines[s + 1].find('Conv.')
      credit_idx = lines[s].find('Credit')

      specs = [
          (0, 7),
          (7, code_idx + 6),
          (code_idx + 6, order_type_idx),
          (isin_idx - 8, isin_idx + 7),
          (type_idx, currency_idx),
          (currency_idx, currency_idx + 6),
          (currency_idx + 6, price_idx),
          (price_idx, price_idx + 12),
          (price_idx + 12, conv_idx),
          (conv_idx, conv_idx + 9),
          (credit_idx - 1, credit_idx + 13),
      ]

      df = pd.read_fwf(
          io.StringIO('\n'.join(lines[s + 3:s + end])),
          colspecs=specs,
          names=[
              'Date',
              'Id',
              'Details',
              'ISIN',
              'Type',
              'Currency',
              'Number',
              'Price',
              'Charges',
              'Conv Rate',
              'Amount',
          ],
          dtype=str,
      )
      df['Account Currency'] = currency
      dfs.append(df)
    else:
      isin_idx = lines[s + 1].find('ISIN')
      code_idx = lines[s + 1].find('Deal')
      order_type_idx = lines[s + 1].find('Type')
      type_idx = lines[s + 1].find('Transaction')
      quantity_idx = lines[s + 1].find('Quantity')
      price_idx = lines[s + 1].find('Dealing')
      credit_idx = lines[s].find('Credit')

      specs = [
          (0, 7),
          (7, code_idx + 6),
          (code_idx + 6, order_type_idx),
          (isin_idx - 8, isin_idx + 8),
          (type_idx, quantity_idx),
          (quantity_idx, price_idx),
          (price_idx, price_idx + 12),
          (price_idx + 12, credit_idx - 1),
          (credit_idx - 1, credit_idx + 17),
      ]

      df = pd.read_fwf(
          io.StringIO('\n'.join(lines[s + 3:s + end])),
          colspecs=specs,
          names=[
              'Date',
              'Id',
              'Details',
              'ISIN',
              'Type',
              'Number',
              'Price',
              'Charges',
              'Amount',
          ],
          dtype=str,
      )
      df['Currency'] = currency
      df['Account Currency'] = currency
      df['Conv Rate'] = math.nan
      dfs.append(df)
  return pd.concat(dfs)


def pdf_to_table(file: str, lines: list[str]) -> pd.DataFrame:
  activity_start = [i for i, l in enumerate(lines) if ' ACCOUNT ACTIVITY' in l]
  dfs: list[pd.DataFrame] = []
  for s, e in zip(activity_start, activity_start[1:] + [len(lines)]):
    dfs.append(
        account_activity_to_table(lines[s].split(' ')[0], lines[s + 1:e]))
  return pd.concat(dfs)


class IgImporter(importer.Importer):
  """Importer for IG Trading platform statements (text format).

  Parses text-converted PDF monthly statements to extract:
  - Stock trades with currency conversion if applicable
  - Cash deposits and withdrawals
  - Dividend and interest payments
  - Balance assertions at statement date

  Args:
    filepath_filter: Regex pattern to match input files.
    account_oracle: AccountOracle for generating account names.
    isin_lookup: Mapping from ISIN codes or description strings to commodity symbols.
    base_dir: Base directory for resolving relative file paths.
  """

  def __init__(
      self,
      filepath_filter: str,
      account_oracle: AccountOracle,
      isin_lookup: dict[str, str],
      base_dir: str,
  ):
    self.filepath_filter = filepath_filter
    self.account_oracle = account_oracle
    self.isin_lookup = isin_lookup
    self.base_dir = base_dir

  @override
  def identify(self, filepath: str):
    return re.fullmatch(
        self.filepath_filter,
        os.path.relpath(filepath, self.base_dir)) is not None

  @override
  def account(self, filepath: str):
    return None

  @override
  def deduplicate(self, entries: Entries, existing: Entries) -> None:
    return

  @override
  def extract(self, filepath: str, existing: Entries) -> Directives:
    lines = [l for l in Path(filepath).read_text().split('\n')]
    df: pd.DataFrame = pdf_to_table(filepath, lines)
    df['Date'] = pd.to_datetime(
        df['Date'], errors='coerce', format='%d%b%y').dt.date
    df = df.dropna(subset=['Date'])

    directives: list[Directive] = []
    transfers = None
    for r in df.to_dict(orient='records'):
      if r['Type'] == 'Cash In' or r['Type'] == 'Cash Out':
        transaction = process_cash_transaction(
            r,
            self.account_oracle.cash_account(),
            self.account_oracle.transfers_account(),
            set(),
        )
        directives.append(transaction)
        continue

      if r['Type'] == 'Dividend':
        symbol = self.isin_lookup[r['Details']]
        transaction = process_cash_transaction(
            r,
            self.account_oracle.cash_account(),
            self.account_oracle.distribution_account(symbol),
            set(),
        )
        directives.append(transaction)
        continue

      if r['Type'] == 'Sold' or r['Type'] == 'Bought':
        transaction = process_investment_transaction(
            r,
            self.account_oracle,
            self.isin_lookup,
        )
        directives.append(transaction)
        continue

      if r['Type'] == 'Currency':
        transfers = transfers or Transaction(
            meta=new_metadata(filepath, 1),
            date=r['Date'],
            flag='*',
            payee=None,
            narration='Transfer',
            tags=frozenset(),
            links=frozenset(),
            postings=[],
        )
        posting = Posting(
            account=self.account_oracle.cash_account(),
            units=Amount(
                Decimal(r['Amount'].replace(',', '')), r['Account Currency']),
            cost=None,
            price=None,
            flag=None,
            meta=None,
        )
        transfers.postings.append(posting)
        continue

      if r['Type'] == 'Exchange' or r['Details'].startswith('Custody Fee'):
        transaction = process_cash_transaction(
            r,
            self.account_oracle.cash_account(),
            self.account_oracle.account_fees_account(),
            set(),
        )
        directives.append(transaction)
        continue

      if r['Type'] == 'Transfer':
        # All transfers should be done manually.
        continue

      print(r, file=sys.stderr)
      raise Exception('Unknown transaction')

    if transfers:
      assert len(transfers.postings) == 2
      rate = -transfers.postings[1].units.number / transfers.postings[
          0].units.number
      transfers.postings[0] = Posting(
          account=transfers.postings[0].account,
          units=transfers.postings[0].units,
          cost=None,
          price=Amount(rate, transfers.postings[1].units.currency),
          flag=None,
          meta=None,
      )
      directives.append(transfers)

    try:
      find(lines, 'Printed at 23')
      nextday = timedelta(days=1)
    except StopIteration:
      nextday = timedelta(days=0)

    balance_date = datetime.strptime(lines[1].strip(),
                                     '%d %B %Y').date() + nextday
    balance = Decimal(lines[find(lines,
                                 'Cash Balance GBP')].split(' ')[-1].replace(
                                     ',', ''))
    directive = Balance(
        meta=new_metadata(filepath, 1),
        date=balance_date,
        amount=Amount(balance, 'GBP'),
        account=self.account_oracle.cash_account(),
        diff_amount=None,
        tolerance=None,
    )
    directives.append(directive)

    return directives
