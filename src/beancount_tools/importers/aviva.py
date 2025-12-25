"""Importer for Aviva pension statements.

Aviva is a UK pension provider. This importer parses yearly PDF statements
(converted to text) containing:
- Cash contributions (employer and personal)
- Management charges
- Buy/sell transactions for underlying funds
"""
from decimal import Decimal
from typing import override
import datetime
import io
import math
import re

from beancount import Amount
from beancount import Directive
from beancount import Directives
from beancount import new_metadata
from beancount import Posting
from beancount.core.data import Entries
from beancount.core.data import Transaction
from beangulp import importer
import pandas as pd

from beancount_tools.importers.account_lookup import AccountOracle


def process_cash_transaction(
    c: dict,
    first_account: str,
    second_account: str,
) -> Transaction:
  date = datetime.datetime.strptime(
      re.sub(r'[^\d/]', r'', c['Date']), '%d/%m/%Y').date()
  raw = str(c['Amount'])
  amount = Amount(Decimal(raw.replace('£', '').replace(',', '')), 'GBP')
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
      date=date,
      flag='*',
      payee=None,
      narration=c.get('Type of contribution', c.get('Description', '')),
      tags=frozenset(),
      links=frozenset(),
      postings=[first, second],
  )


def process_investment_transaction(
    t: dict,
    account_oracle: AccountOracle,
    buy: bool,
) -> Transaction:
  multipler = Decimal('1') if buy else Decimal('-1')

  date = datetime.datetime.strptime(t['Date'], '%d/%m/%Y').date()
  symbol = t['ISIN']

  raw_units = str(t['Number'])
  raw_price = str(t['Price'])
  raw_value = str(t['Total'])

  price = Decimal(raw_price.replace(',', '')) / Decimal('100')
  first_posting = Posting(
      account=account_oracle.asset_account(symbol),
      units=Amount(multipler * Decimal(raw_units.replace(',', '')), symbol),
      cost=None,
      price=Amount(price, 'GBP'),
      flag=None,
      meta=None,
  )
  second_posting = Posting(
      account=account_oracle.cash_account(),
      units=Amount(multipler * -Decimal(raw_value.replace(',', '')), 'GBP'),
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )
  postings = [
      first_posting,
      second_posting,
  ]
  return Transaction(
      meta=new_metadata('foo', 1),
      date=date,
      flag='*',
      payee=None,
      narration='BUY' if buy else 'SELL',
      tags=frozenset(),
      links=frozenset(),
      postings=postings,
  )


def pdf_to_table_old(lines: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
  start_idx = next(
      i for i, obj in enumerate(lines) if 'Paid In (£)   Paid Out (£)' in obj)
  end_idx = next(i for i, obj in enumerate(lines) if 'Please note: ' in obj)
  pruned = lines[start_idx + 1:end_idx]

  date_idx = lines[start_idx].find('Date of')
  desc_idx = lines[start_idx].find('Description')
  in_idx = lines[start_idx].find('Paid In')
  balance_idx = lines[start_idx].find('Balance')

  cash = pd.read_fwf(
      io.StringIO('\n'.join(pruned)),
      colspecs=[
          (date_idx, date_idx + 11),
          (desc_idx, in_idx),
          (in_idx, balance_idx - 6),
          (balance_idx - 6, balance_idx + 100),
      ],
      names=['Date', 'Description', 'Amount', 'Balance'],
      dtype=str,
  )

  investments_end = next(
      i for i, l in enumerate(lines) if 'Your selected retirement date  ' in l)
  starts = [
      i for i, obj in enumerate(lines[:investments_end]) if 'Order type' in obj
  ]
  lens = [
      next(i
           for i, l in enumerate(lines[i:investments_end])
           if 'Date produced' in l)
      for i in starts
  ]

  investments = []
  for s, l in zip(starts, lens):
    bs_idx = lines[s].find('Buy / Sell')
    date_idx = lines[s].find('Transaction')
    isin_idx = lines[s].find('ISIN')
    number_idx = lines[s].find('Number of')
    price_idx = lines[s].find('Unit / Share')
    commission_idx = lines[s].find('Commission')
    amount_idx = lines[s].find('Total')
    pruned = lines[s + 4:s + l]

    investments.append(
        pd.read_fwf(
            io.StringIO('\n'.join(pruned)),
            colspecs=[
                (0, bs_idx + 10),
                (date_idx, date_idx + 11),
                (isin_idx - 5, isin_idx + 9),
                (number_idx, number_idx + 10),
                (price_idx, price_idx + 13),
                (commission_idx, commission_idx + 13),
                (commission_idx + 13, amount_idx + 100),
            ],
            names=[
                'B/S', 'Date', 'ISIN', 'Number', 'Price', 'Commission', 'Total'
            ],
            dtype=str,
        ))
  return cash, pd.concat(investments)


def pdf_to_table_new(lines: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
  end = next(i for i, l in enumerate(lines)
             if 'Your investment transaction history' in l)
  cash = lines[:end]
  starts = [i for i, obj in enumerate(cash) if 'Type of contribution' in obj]
  ends = starts[1:] + [end]

  dfs = []
  for s, e in zip(starts, ends):
    date_idx = lines[s].find('Date')
    amount_idx = lines[s].find('Amount')
    pruned = lines[s + 1:e]

    dfs.append(
        pd.read_fwf(
            io.StringIO('\n'.join(pruned)),
            colspecs=[
                (0, date_idx + 7),
                (date_idx + 7, amount_idx - 4),
                (amount_idx - 4, amount_idx + 100),
            ],
            names=['Date', 'Description', 'Amount'],
            dtype=str,
        ))

  investments_end = next(i - 3
                         for i, l in enumerate(lines)
                         if 'Your Investment Account update' in l or
                         'Your future pension in today' in l)
  investments = lines[:investments_end]

  starts = [i for i, obj in enumerate(investments) if 'Unit/' in obj]
  ends = starts[1:] + [investments_end]

  investments = []
  for s, e in zip(starts, ends):
    bs_idx = lines[s].find('Buy / Sell')
    date_idx = lines[s].find('Transaction')
    isin_idx = lines[s].find('ISIN')
    number_idx = lines[s].find('Number')
    price_idx = lines[s].find('Unit/')
    commission_idx = lines[s].find('Charges')
    amount_idx = lines[s].find('Value')
    pruned = lines[s + 4:e]

    investments.append(
        pd.read_fwf(
            io.StringIO('\n'.join(pruned)),
            colspecs=[
                (0, bs_idx + 10),
                (date_idx - 5, date_idx + 11),
                (isin_idx - 1, isin_idx + 14),
                (number_idx - 2, number_idx + 10),
                (price_idx - 1, price_idx + 6),
                (commission_idx, commission_idx + 6),
                (commission_idx + 7, amount_idx + 100),
            ],
            names=[
                'B/S', 'Date', 'ISIN', 'Number', 'Price', 'Commission', 'Total'
            ],
            dtype=str,
        ))
  return pd.concat(dfs), pd.concat(investments)


def pdf_to_table(file: str) -> tuple[pd.DataFrame, pd.DataFrame]:
  with open(file, 'r') as f:
    lines = [l for l in f.read().split('\n')]

  if 'Yearly statement for your Flexible Retirement Account' in lines[0]:
    return pdf_to_table_old(lines)

  return pdf_to_table_new(lines)


class AvivaPensionImporter(importer.Importer):
  """Importer for Aviva yearly pension statements (text format).

  Parses text-converted PDF statements to extract:
  - Employer contributions
  - Regular payments
  - Management charges
  - Fund buy/sell transactions

  Args:
    account_oracle: AccountOracle for generating account names.
  """

  def __init__(
      self,
      account_oracle: AccountOracle,
  ):
    self.account_oracle = account_oracle

  @override
  def identify(self, filepath: str):
    return filepath.endswith('.txt') and 'Aviva' in filepath

  @override
  def account(self, filepath: str):
    return ''

  @override
  def deduplicate(self, entries: Entries, existing: Entries) -> None:
    return

  @override
  def extract(self, filepath: str, existing: Entries) -> Directives:
    cash, investments = pdf_to_table(filepath)
    directives: list[Directive] = []
    for r in cash.to_dict(orient='records'):
      if r['Date'] == 'transaction':
        continue
      if isinstance(r['Date'], float) and math.isnan(r['Date']):
        continue
      if r['Date'] == 'Date produc':
        continue

      desc = r['Description']
      if 'Balance brought forward' in desc or 'Balance carried forward' in desc:
        continue

      if desc.startswith('Buy'):
        continue
      if desc.startswith('Sell'):
        continue
      if desc.startswith('Employer') or 'Regular payment' in desc:
        transaction = process_cash_transaction(
            r,
            self.account_oracle.cash_account(),
            self.account_oracle.transfers_account(),
        )
        directives.append(transaction)
        continue
      if 'annual management charge' in desc:
        transaction = process_cash_transaction(
            r,
            self.account_oracle.cash_account(),
            self.account_oracle.account_fees_account(),
        )
        directives.append(transaction)
        continue
      print(r)
      raise Exception('Unknown cash transaction')

    for r in investments.to_dict(orient='records'):
      date = r['Date']
      if isinstance(date, float) and math.isnan(date):
        continue
      if date == 'date / tim':
        continue
      if r['Price'] == '(pence)':
        continue
      if isinstance(date, str) and (date.endswith('PM') or date.endswith('AM')):
        continue

      b_s = r['B/S']
      if b_s == 'BUY' or b_s == 'Buy' or b_s == 'SELL' or b_s == 'Sell':
        assert r['Commission'] == '0.00'
        directives.append(
            process_investment_transaction(r, self.account_oracle,
                                           b_s == 'BUY' or b_s == 'Buy'))
        continue

      print(r)
      raise Exception('Unknown investment transaction')

    return directives
