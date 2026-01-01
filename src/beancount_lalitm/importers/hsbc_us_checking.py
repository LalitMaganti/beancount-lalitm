"""Importer for HSBC US checking account statements.

Parses text-converted PDF bank statements to extract:
- All account transactions (deposits, withdrawals)
- Transaction descriptions and amounts in USD
"""
from beancount.core.data import Amount
from beancount.core.data import Directive
from beancount.core.data import Entries
from beancount.core.data import new_metadata
from beancount.core.data import Posting
from beancount.core.data import Transaction
from beangulp import importer
from beangulp.cache import _FileMemo
from decimal import Decimal
import io
import math
import pandas as pd


def pdf_to_table(file: str) -> pd.DataFrame:
  with open(file, 'r') as f:
    lines = [l for l in f.read().split('\n')]

  start_idx = next(i for i, obj in enumerate(lines) if 'DESCRIPTION OF ' in obj)
  det = lines[start_idx].find('DESCRIPTION OF TRANSACTIONS')
  in_idx = lines[start_idx].find('ADDITIONS')
  out = lines[start_idx].find('SUBTRACTIONS')
  b_idx = lines[start_idx].find('BALANCE')

  dfs = []
  starts = [
      i for i, obj in enumerate(lines)
      if 'OPENING BALANCE' in obj or 'CONTINUED FROM PREVIOUS PAGE' in obj
  ]
  ends = [
      i for i, obj in enumerate(lines)
      if '      ENDING BALANCE' in obj or 'CONTINUED ON NEXT PAGE' in obj
  ]
  assert len(starts) == len(ends)
  for start, end in zip(starts, ends):
    pruned = lines[start + 1:end]
    dfs.append(
        pd.read_fwf(
            io.StringIO('\n'.join(pruned)),
            colspecs=[
                (0, 9),
                (det - 1, det + 60),
                (in_idx - 3, in_idx + 15),
                (out - 3, out + 15),
                (b_idx - 5, b_idx + 20),
            ],
            names=['Date', 'Details', 'Paid in', 'Paid out', 'Balance'],
        ))

  return pd.concat(dfs)


class HsbcUsCheckingImporter(importer.ImporterProtocol):
  """Importer for HSBC US checking account statements (text format).

  Args:
    account: The beancount account path for this checking account.
  """

  def __init__(self, account: str):
    self.account = account

  def identify(self, file: _FileMemo):
    return file.name.endswith('.txt')

  def extract(self, file: _FileMemo,
              existing_entries: Entries | None) -> list[Directive]:
    df = pdf_to_table(file.name)
    df = df.reset_index(drop=True)

    res = []
    it = iter(df.iterrows())
    for _, row in it:
      if isinstance(row['Paid out'], float) and math.isnan(row['Paid out']) and \
        isinstance(row['Paid in'], float) and math.isnan(row['Paid in']):
        continue
      details = row['Details']
      res.append((
          row['Date'],
          details,
          row['Paid in'],
          row['Paid out'],
          row['Balance'],
      ))

    out = pd.DataFrame(res, columns=df.columns)
    out.loc[:, 'Date'] = pd.to_datetime(
        out.loc[:, 'Date'].ffill(), format='%m/%d/%y')

    directives = []
    for _, row in out.iterrows():
      units = str(row['Paid in']) if not (
          isinstance(row['Paid in'], float) and
          math.isnan(row['Paid in'])) else '-' + str(row['Paid out'])
      dec = Decimal(units.replace(',', ''))
      if dec == 0:
        continue
      directives.append(
          Transaction(
              meta=new_metadata(file.name, 1),
              date=row['Date'].date(),
              flag='*',
              payee=None,
              narration=row['Details'],
              tags=set(),
              links=set(),
              postings=[
                  Posting(
                      account=self.account,
                      units=Amount(dec, 'USD'),
                      cost=None,
                      price=None,
                      flag=None,
                      meta=None,
                  ),
              ],
          ))
    return directives
