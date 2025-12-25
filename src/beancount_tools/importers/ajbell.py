"""Importers for AJ Bell investment platform.

AJ Bell is a UK investment platform offering ISAs, GIAs, and SIPPs.
This module provides importers for:
- Transaction contract notes (PDF): Buy/sell confirmations
- Cash transaction history (CSV): Deposits, withdrawals, dividends, fees
"""
from pathlib import Path
from typing import override
from beancount.core.data import Amount
from beancount.core.data import Directive
from beancount.core.data import Directives
from beancount.core.data import Entries
from beancount.core.data import Posting
from beancount.core.data import Transaction
from beancount.core.data import new_metadata
from beangulp import importer
import csv
import datetime
from decimal import Decimal
import pdftotext
import re
import sys

from beancount_tools.importers.account_lookup import AccountOracle


def process_cash_transaction(
    c: dict,
    account: str,
    transfers_account: str,
    tags: set[str],
    col: str,
) -> Transaction:
  date = datetime.datetime.strptime(c['Date'], '%d/%m/%Y').date()
  amount = Amount(Decimal(c[col]), 'GBP')
  first = Posting(
      account=account,
      units=amount,
      cost=None,
      price=None,
      flag=None,
      meta=None,
  )
  second = Posting(
      account=transfers_account,
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
      narration=c['Description'],
      tags=tags,
      links=set(),
      postings=[first, second],
  )


def pdf_to_text(file: str) -> str:
  with open(file, "rb") as f:
    return pdftotext.PDF(f, physical=True)[0]


class AjTransactionsImporter(importer.Importer):
  """Importer for AJ Bell transaction contract notes (PDF).

  Parses PDF contract notes for buy/sell transactions, extracting:
  - Trade date, quantity, price, and settlement currency
  - Commission charges
  - Accrued interest (for bonds)

  Args:
    account_id: The AJ Bell account ID (e.g., 'ABBPRVD' for GIA, 'ABBPRVI' for ISA).
    account_oracle: AccountOracle for generating account names.
    sedol_symbol_map: Mapping from SEDOL codes to your commodity symbols.
  """

  def __init__(
      self,
      account_id: str,
      account_oracle: AccountOracle,
      sedol_symbol_map: dict[str, str],
  ):
    self.account_id = account_id
    self.account_oracle = account_oracle
    self.sedol_symbol_map = sedol_symbol_map

  @override
  def identify(self, file: str):
    if not file.endswith('.pdf'):
      return False
    return 'aj' in file and 'aj-docs' not in file and self.account_id in pdf_to_text(
        file)

  @override
  def account(self, _: str):
    return None

  @override
  def deduplicate(self, _: Entries, __: Entries) -> None:
    return

  @override
  def extract(self, file: str, _: Entries) -> list[Directive]:
    res = pdf_to_text(file)
    lines = [
        re.sub(' +', ' ', line.strip()) for line in res.splitlines() if line
    ]
    if 'Deal date Time Settlement date Bought or Sold Sedol Reference' in lines:
      index = lines.index(
          'Deal date Time Settlement date Bought or Sold Sedol Reference')
      date, _, _, b_or_s, sedol, _ = lines[index + 1].split(' ')
      symbol = self.sedol_symbol_map[sedol]
      assert b_or_s == 'Bought' or b_or_s == 'Sold'

      multiplier = Decimal('1') if b_or_s == 'Bought' else Decimal('-1')
      _, quantity, price, _, currency = lines[index + 5].replace(' Ex-Div',
                                                                 '').split(' ')
      _, _, charge, charge_currency = lines[lines.index('_____________') -
                                            1].split(' ')
      _, _, total, total_currency = lines[lines.index('_____________') +
                                          1].split(' ')

      date = datetime.datetime.strptime(date, '%d/%m/%y').date()
      postings = [
          Posting(
              account=self.account_oracle.asset_account(symbol),
              units=Amount(multiplier * Decimal(quantity.replace(',', '')),
                           symbol),
              cost=None,
              price=Amount(Decimal(price.replace(',', '')), currency),
              flag=None,
              meta=None,
          ),
          Posting(
              account=self.account_oracle.cash_account(),
              units=Amount(multiplier * -Decimal(total.replace(',', '')),
                           total_currency),
              cost=None,
              price=None,
              flag=None,
              meta=None,
          ),
          Posting(
              account=self.account_oracle.commission_account(symbol),
              units=Amount(Decimal(charge.replace(',', '')), charge_currency),
              cost=None,
              price=None,
              flag=None,
              meta=None,
          )
      ]

      if 'Plus accrued interest' in lines:
        _, _, interest_price, interest_currency = lines[
            lines.index('Plus accrued interest') + 1].split(' ')
        posting = Posting(
            account=self.account_oracle.distribution_account(symbol),
            units=Amount(multiplier * Decimal(interest_price.replace(',', '')),
                         interest_currency),
            cost=None,
            price=None,
            flag=None,
            meta=None,
        )
        postings.append(posting)

      return [
          Transaction(
              meta=new_metadata('foo', 1),
              date=date,
              flag='*',
              payee=None,
              narration=f'{b_or_s} {quantity} {symbol}',
              tags=set(),
              links=set(),
              postings=postings,
          )
      ]

    print('\n'.join(lines), file=sys.stderr)
    raise Exception('Unknown transaction type')


class AjCashImporter(importer.Importer):
  """Importer for AJ Bell cash transaction history (CSV).

  Parses CSV exports of cash transactions, handling:
  - Deposits and withdrawals
  - Dividend payments
  - Interest income
  - Custody and FX charges
  - Inter-product transfers

  Args:
    filename_filter: Regex pattern to match input files.
    account_oracle: AccountOracle for generating account names.
    distribution_description_to_symbol_map: Mapping from dividend description
        strings to your commodity symbols.
  """

  def __init__(
      self,
      filename_filter: str,
      account_oracle: AccountOracle,
      distribution_description_to_symbol_map: dict[str, str],
  ):
    self.filename_filter = filename_filter
    self.account_oracle = account_oracle
    self.distribution_description_to_symbol_map = distribution_description_to_symbol_map

  @override
  def identify(self, file: str):
    res = re.fullmatch(self.filename_filter, file)
    return file.endswith(
        '.csv') and res and '"Payment (GBP)","Balance (GBP)"' in Path(file).read_text()

  @override
  def account(self, _: str):
    return None

  @override
  def deduplicate(self, _: Entries, __: Entries) -> None:
    return

  @override
  def extract(self, file: str, _: Entries) -> Directives:
    reader = csv.DictReader(Path(file).read_text(encoding='utf-8-sig').splitlines())

    directives: list[Directive] = []
    for row in reader:
      if row['Description'].startswith(
          'Purchase') or row['Description'].startswith('Sale'):
        continue

      if row['Description'].startswith('Faster Payment In') or \
          row['Description'].startswith('Debit Card Payment') or \
          row['Description'].startswith('Subscription') or \
          row['Description'].startswith('Transfer From'):
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.transfers_account(),
            set(),
            'Receipt (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith('Cash Withdrawal'):
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.transfers_account(),
            set(),
            'Payment (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith('Shares Custody Charge') or row[
          'Description'].startswith('Account charge for shares'):
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.account_fees_account(),
            set(),
            'Payment (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith(
          'DIVIDEND') or row['Description'].startswith('Dividend'):
        desc = row['Description'].split('   ')[1]
        symbol = self.distribution_description_to_symbol_map[desc]
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.distribution_account(symbol),
            set(),
            'Receipt (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith('Gross interest'):  #
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.account_interest_account(),
            set(),
            'Receipt (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith('* BALANCE'):
        continue

      if row['Description'].startswith('FX Charge'):
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.account_fees_account(),
            set(),
            'Payment (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].startswith('Transfer Between Products'):
        transaction = process_cash_transaction(
            row,
            self.account_oracle.cash_account(),
            self.account_oracle.transfers_account(),
            set(),
            'Receipt (GBP)' if row['Payment (GBP)'] == '0' else 'Payment (GBP)',
        )
        directives.append(transaction)
        continue

      if row['Description'].endswith('Redemption'):
        continue

      print(row, file=sys.stderr)
      raise Exception('Unknown transaction type')

    return directives
