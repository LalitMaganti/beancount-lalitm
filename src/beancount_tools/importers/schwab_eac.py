from pathlib import Path
from beancount.core.data import Amount
from beancount.core.data import Directive
from beancount.core.data import Directives
from beancount.core.data import Entries
from beancount.core.data import new_metadata
from beancount.core.data import Posting
from beancount.core.data import Transaction
from beangulp import importer
from decimal import Decimal
from typing import override
import datetime
import io
import os
import pandas as pd
import re

from beancount_tools.importers.account_lookup import AccountOracle


class SchwabEacImporter(importer.Importer):
  """Importer for Schwab Equity Award Center (EAC) statements.

  Args:
    account_currency: Currency for the account (e.g., 'USD').
    filename_filter: Regex pattern to match input files.
    account_oracle: AccountOracle for generating account names.
    base_dir: Base directory for resolving relative file paths.
    stock_symbol: The stock symbol for this EAC account (e.g., 'GOOG').
  """

  def __init__(
      self,
      account_currency: str,
      filename_filter: str,
      account_oracle: AccountOracle,
      base_dir: str,
      stock_symbol: str,
  ):
    self.account_currency = account_currency
    self.filename_filter = filename_filter
    self.account_oracle = account_oracle
    self.base_dir = base_dir
    self.stock_symbol = stock_symbol

  @override
  def identify(self, file: str):
    return re.fullmatch(
        self.filename_filter,
        os.path.relpath(file, self.base_dir))

  @override
  def account(self, _: str):
    return None

  @override
  def deduplicate(self, _: Entries, __: Entries) -> None:
    return

  @override
  def extract(self, file: str, _: Entries) -> Directives:
    lines = Path(file).read_text().split('\n')

    starts = [
        i for i, obj in enumerate(lines)
        if 'Activity' in obj and 'Description' in obj
    ]
    dfs = []
    for s in starts:
      date = lines[s + 1].find('Date')
      act = lines[s].find('Activity')
      fmv = lines[s + 1].find('FMV')
      shares = lines[s].find('Shares')
      price = lines[s + 1].rfind('Price')
      proceeds = lines[s + 1].rfind('Proceeds')
      pruned = lines[s + 2:]
      for i, l in enumerate(pruned):
        if 'No stock transactions' in l:
          break
        if l != '':
          continue
        dfs.append(
            pd.read_fwf(
                io.StringIO('\n'.join(pruned[:i])),
                colspecs=[
                    (date - 3, date + 8),
                    (act - 2, act + 10),
                    (fmv - 5, fmv + 8),
                    (shares - 3, shares + 8),
                    (price - 5, price + 7),
                    (proceeds - 3, proceeds + 10),
                ],
                names=[
                    'Date', 'Activity', 'FMV', 'Shares', 'Price', 'Proceeds'
                ],
                converters={
                    0: str,
                    1: str,
                    2: str,
                    3: str,
                    4: str,
                    5: str,
                }))
        break

    directives: list[Directive] = []
    starts = [
        i for i, obj in enumerate(lines) if 'Cash Transaction Summary' in obj
    ]
    for s in starts:
      date = lines[s + 1].find('Transaction')
      amo = lines[s + 2].find('Amount')
      desc = lines[s + 2].find('Description')
      fee = lines[s + 2].find('Fee')
      pruned = lines[s + 4:]
      for i, l in enumerate(pruned):
        if 'No cash transactions' in l:
          break
        if l != '':
          continue
        df = pd.read_fwf(
            io.StringIO('\n'.join(pruned[:i])),
            colspecs=[
                (date, date + 13),
                (amo - 12, amo + 14),
                (desc - 6, desc + 16),
                (fee - 11, fee + 11),
            ],
            names=['Date', 'Amount', 'Description', 'Fee'],
            converters={
                0: str,
                1: str,
                2: str,
                3: str,
            })
        it = iter(df.iterrows())
        for _, row in it:
          try:
            date = datetime.datetime.strptime(row['Date'].replace('*', ''),
                                              '%m/%d/%y').date()
          except Exception:
            date = datetime.datetime.strptime(row['Date'].replace('*', ''),
                                              '%Y-%m-%d').date()
            _, row = next(it)
            _ = next(it)
          amount = row['Amount'].replace('(', '').replace(')', '').replace(
              '$', '').replace(',', '')
          fee = row['Fee'].replace('$', '').replace(',', '')
          if row['Description'] == 'Sale Proceeds':
            continue
          elif row['Description'] == 'Trade Fee':
            postings = [
                Posting(
                    account=self.account_oracle.cash_account(),
                    units=Amount(-Decimal(fee), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                Posting(
                    account=self.account_oracle.commission_account(self.stock_symbol),
                    units=Amount(Decimal(fee), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ]
          elif row['Description'] == 'Wire':
            multipler = Decimal('-1') if row['Amount'].startswith(
                '(') else Decimal('1')
            postings = [
                Posting(
                    account=self.account_oracle.cash_account(),
                    units=Amount(multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                Posting(
                    account=self.account_oracle.transfers_account(),
                    units=Amount(-multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ]
          elif row['Description'] == 'Dividend':
            multipler = Decimal('-1') if row['Amount'].startswith(
                '(') else Decimal('1')
            postings = [
                Posting(
                    account=self.account_oracle.cash_account(),
                    units=Amount(multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                Posting(
                    account=self.account_oracle.distribution_account(self.stock_symbol),
                    units=Amount(-multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ]
          elif row['Description'] == 'Tax Withholding':
            multipler = Decimal('-1') if row['Amount'].startswith(
                '(') else Decimal('1')
            postings = [
                Posting(
                    account=self.account_oracle.cash_account(),
                    units=Amount(multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
                Posting(
                    account=self.account_oracle.withholding_taxes_account(
                        self.stock_symbol),
                    units=Amount(-multipler * Decimal(amount), 'USD'),
                    cost=None,
                    price=None,
                    flag=None,
                    meta=None,
                ),
            ]
          else:
            raise Exception(f'Unknown activity: {row["Description"]}')
          directives.append(
              Transaction(
                  meta=new_metadata(file, 1),
                  date=date,
                  flag='*',
                  payee=None,
                  narration=row['Description'],
                  tags=set(),
                  links=set(),
                  postings=postings,
              ))
        break

    if not dfs:
      return directives

    out = pd.concat(dfs).reset_index(drop=True)
    it = iter(out.iterrows())
    for _, row in it:
      try:
        date = datetime.datetime.strptime(row['Date'].replace('*', ''),
                                          '%m/%d/%y').date()
      except Exception:
        date = datetime.datetime.strptime(row['Date'].replace('*', ''),
                                          '%Y-%m-%d').date()
        _, row = next(it)
        _ = next(it)
      price = row['Price'].replace('$', '').replace(',', '')
      fmv = row['FMV'].replace('$', '').replace(',', '')
      shares = row['Shares'].replace('(', '').replace(')', '')
      proceeds = str(row['Proceeds']).replace('$', '').replace(',', '')
      if row['Activity'] == 'Deposit':
        transfer_postings = [
            Posting(
                account=self.account_oracle.cash_account(),
                units=Amount(Decimal(fmv) * Decimal(shares), 'USD'),
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
            Posting(
                account=self.account_oracle.stock_revenue_account(),
                units=Amount(-Decimal(fmv) * Decimal(shares), 'USD'),
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ]
        directives.append(
            Transaction(
                meta=new_metadata(file, 1),
                date=date,
                flag='*',
                payee=None,
                narration=row['Activity'],
                tags=set(),
                links=set(),
                postings=transfer_postings,
            ))

        postings = [
            Posting(
                account=self.account_oracle.asset_account(self.stock_symbol),
                units=Amount(Decimal(shares), self.stock_symbol),
                cost=None,
                price=Amount(Decimal(fmv), 'USD'),
                flag=None,
                meta=None,
            ),
            Posting(
                account=self.account_oracle.cash_account(),
                units=Amount(-Decimal(fmv) * Decimal(shares), 'USD'),
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ]
      elif row['Activity'] == 'Sale':
        postings = [
            Posting(
                account=self.account_oracle.asset_account(self.stock_symbol),
                units=Amount(-Decimal(shares), self.stock_symbol),
                cost=None,
                price=Amount(Decimal(price), 'USD'),
                flag=None,
                meta=None,
            ),
            Posting(
                account=self.account_oracle.cash_account(),
                units=Amount(Decimal(proceeds), 'USD'),
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ]
      elif row['Activity'] == 'Stock Split':
        continue
      else:
        raise Exception(f'Unknown activity: {row["Activity"]}')
      directives.append(
          Transaction(
              meta=new_metadata(file, 1),
              date=date,
              flag='*',
              payee=None,
              narration=row['Activity'],
              tags=set(),
              links=set(),
              postings=postings,
          ))
    return directives
