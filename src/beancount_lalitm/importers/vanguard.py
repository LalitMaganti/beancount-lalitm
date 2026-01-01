"""Importer for Vanguard UK investment platform.

Vanguard UK offers ISAs and GIAs with low-cost index funds and ETFs.
This importer parses Excel transaction exports containing:
- Cash deposits and withdrawals
- Fund buy/sell transactions
- Dividend reinvestments
"""
from beancount.core.data import Amount
from beancount.core.data import Directive
from beancount.core.data import Entries
from beancount.core.data import new_metadata
from beancount.core.data import Posting
from beancount.core.data import Transaction
from dataclasses import dataclass
from beangulp import importer
from beangulp.cache import _FileMemo
from decimal import Decimal
import pandas as pd
import sys

from beancount_lalitm.importers.account_lookup import AccountOracle


def process_cash_transaction(
    c: dict,
    first_account: str,
    second_account: str,
    tags: set[str],
) -> Transaction:
  amount = Amount(Decimal(c['Amount']), 'GBP')
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
      tags=tags,
      links=set(),
      postings=[first, second],
  )


def process_investment_transaction(
    t: dict,
    account_oracle: AccountOracle,
    investment_map: dict[str, str],
) -> Transaction:
  symbol = investment_map[t['InvestmentName']]
  first_posting = Posting(
      account=account_oracle.asset_account(symbol),
      units=Amount(Decimal(t['Quantity']), symbol),
      cost=None,
      price=Amount(Decimal(t['Price']), 'GBP'),
      flag=None,
      meta=None,
  )
  second_posting = Posting(
      account=account_oracle.cash_account(),
      units=Amount(-Decimal(t['Cost']).quantize(Decimal('0.01')), 'GBP'),
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
      date=t['Date'],
      flag='*',
      payee=None,
      narration=str(t['TransactionDetails']),
      tags=set(),
      links=set(),
      postings=postings,
  )

@dataclass
class SheetMatcher:
  """Configuration for matching a Vanguard Excel sheet to an account.

  Attributes:
    sheet_name: The exact name of the Excel sheet to match.
    account_oracle: AccountOracle for generating account names.
    investment_map: Mapping from Vanguard investment names to commodity symbols.
  """
  sheet_name: str
  account_oracle: AccountOracle
  investment_map: dict[str, str]


class VanguardImporter(importer.ImporterProtocol):
  """Importer for Vanguard UK Excel transaction exports.

  Supports multiple accounts (ISA, GIA) in a single Excel file by using
  SheetMatcher configurations for each sheet.

  Args:
    matchers: List of SheetMatcher configurations, one per account/sheet.
  """

  def __init__(
      self,
      matchers: list[SheetMatcher]
  ):
    self.matches = matchers

  def identify(self, file: _FileMemo):
    return file.name.endswith('.xlsx') and 'vanguard' in file.name

  def extract(self,
              file: _FileMemo,
              existing_entries: Entries | None = None) -> list[Directive]:
    directives: list[Directive] = []

    for match in self.matches:
      ex = pd.read_excel(file.name, sheet_name=match.sheet_name, dtype='str')
      starts = ex[ex.iloc[:, 0] == 'Date'].index
      ends = ex[(ex.iloc[:, 0] == 'Balance') | (ex.iloc[:, 0] == 'Cost')
                | (ex.iloc[:,
                          0] == 'No transactions found for this product.')].index
      assert len(starts) == 2
      assert len(ends) == 2

      cash = ex.iloc[starts[0]:ends[0], :]
      cash.columns = cash.iloc[0]
      cash = cash.drop(cash.index[0]).dropna(
          axis=1, how='all').reset_index(drop=False)
      cash['Date'] = pd.to_datetime(cash['Date']).dt.date

      investments = ex.iloc[starts[1]:ends[1], :]
      investments.columns = investments.iloc[0]
      investments = investments.drop(investments.index[0]).reset_index(drop=False)
      investments['Date'] = pd.to_datetime(investments['Date']).dt.date

      for r in cash.to_dict(orient='records'):
        desc: str = r['Details']
        if desc.startswith(
            'Deposit'
        ) or 'withdrawal' in desc or 'Withdrawal' in desc or 'Cash transfer' in desc or desc.startswith(
            'Payment'):
          directives.append(
              process_cash_transaction(
                  r,
                  match.account_oracle.cash_account(),
                  match.account_oracle.transfers_account(),
                  set(),
              ))
          continue
        if desc.startswith('DIV'):
          directives.append(
              process_cash_transaction(
                  r,
                  match.account_oracle.cash_account(),
                  match.account_oracle.distribution_account('UNKNOWN-DIV'),
                  set(),
              ))
          continue
        if desc == 'Cash Account Interest':
          directives.append(
              process_cash_transaction(
                  r,
                  match.account_oracle.cash_account(),
                  match.account_oracle.account_interest_account(),
                  set(),
              ))
          continue
        if desc.startswith('Account Fee'):
          directives.append(
              process_cash_transaction(
                  r,
                  match.account_oracle.cash_account(),
                  match.account_oracle.account_fees_account(),
                  set(),
              ))
          continue
        if desc.startswith('Bought') or desc.startswith('Sold'):
          continue
        print(r, file=sys.stderr)
        raise Exception('Unknown cash transaction')

      for r in investments.to_dict(orient='records'):
        directives.append(
            process_investment_transaction(r, match.account_oracle,
                                          match.investment_map))

    return directives
