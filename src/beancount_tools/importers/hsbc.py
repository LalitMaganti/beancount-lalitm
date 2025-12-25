"""Importer for HSBC UK current account statements.

Parses text-converted PDF bank statements to extract:
- All account transactions (payments, receipts)
- Balance carried forward assertions
"""
from beancount.core.data import Amount
from beancount.core.data import Balance
from beancount.core.data import Directive
from beancount.core.data import Entries
from beancount.core.data import new_metadata
from beancount.core.data import Posting
from beancount.core.data import Transaction
from beangulp import importer
from beangulp.cache import _FileMemo
from decimal import Decimal
import datetime
import dataclasses
import io
import math
import pandas as pd


@dataclasses.dataclass
class Context:
  description: str


def pdf_to_table(file: str) -> pd.DataFrame:
  with open(file, 'r') as f:
    lines = [l for l in f.read().split('\n')]

  dfs = []
  for idx in [i for i, obj in enumerate(lines) if 'Date      ' in obj]:
    det = lines[idx].find('Pay')
    out = lines[idx].find('Paid o')
    in_idx = lines[idx].find('Paid i')
    b_idx = lines[idx].find('Balance')

    pruned = lines[idx + 1:]
    start = next(
        i for i, obj in enumerate(pruned) if 'BALANCE BROUGHT FORWARD' in obj or '       .' in obj)
    pruned = pruned[start + 1:]
    end = next(
        i for i, obj in enumerate(pruned) if 'BALANCE CARRIED FORWARD' in obj)
    pruned = pruned[:end]

    dfs.append(
        pd.read_fwf(
            io.StringIO('\n'.join(pruned)),
            colspecs=[
                (0, 9),
                (det - 1, det + 3),
                (det + 3, det + 25),
                (out - 3, out + 12),
                (in_idx - 3, in_idx + 12),
                (b_idx - 10, b_idx + 10),
            ],
            names=['Date', 'Code', 'Details', 'Paid out', 'Paid in', 'Balance'],
        ))
  return pd.concat(dfs)


class HsbcImporter(importer.ImporterProtocol):
  """Importer for HSBC UK current account statements (text format).

  Parses text-converted PDF statements. Transactions are extracted with
  balance assertions at statement end dates.

  Args:
    account: The beancount account path for this bank account.
  """

  def __init__(self, account: str):
    self.account = account

  def identify(self, file: _FileMemo):
    return file.name.endswith('.txt')

  def extract(self, file: _FileMemo,
              existing_entries: Entries | None) -> list[Directive]:
    df = pdf_to_table(file.name)
    df['File'] = file.name
    df = df.reset_index(drop=True)

    res = []
    it = iter(df.iterrows())
    for _, row in it:
      assert isinstance(row['Code'], str)
      orig_row = row
      details = row['Details']
      while (isinstance(row['Paid out'], float) and math.isnan(row['Paid out'])) and \
        (isinstance(row['Paid in'], float) and math.isnan(row['Paid in'])) :
        assert orig_row['File'] == row['File']
        try:
          _, row = next(it)
        except:
          raise
        details += ' ' + row['Details']
      res.append((
          orig_row['Date'],
          orig_row['Code'],
          details,
          row['Paid out'],
          row['Paid in'],
          row['Balance'],
          orig_row['File'],
      ))

    out = pd.DataFrame(res, columns=df.columns)
    out.loc[:, 'Date'] = pd.to_datetime(
        out['Date'].ffill(), format='%d %b %y')

    directives = []
    for _, row in out.iterrows():
      units = str(row['Paid in']) if not (
          isinstance(row['Paid in'], float) and
          math.isnan(row['Paid in'])) else '-' + str(row['Paid out'])
      directives.append(
          Transaction(
              meta=new_metadata(row['File'], 1),
              date=row['Date'].date(),
              flag='*',
              payee=None,
              narration=row['Details'],
              tags=set(),
              links=set(),
              postings=[
                  Posting(
                      account=self.account,
                      units=Amount(Decimal(units.replace(',', '')), 'GBP'),
                      cost=None,
                      price=None,
                      flag=None,
                      meta=None,
                  ),
              ],
          ))
      if not (isinstance(row['Balance'], float) and math.isnan(row['Balance'])):
        res = str(row['Balance']).replace(',', '')
        if res.endswith(' D'):
          res = res.replace(' D', '')
          amount = -Decimal(res)
        else:
          amount = Decimal(res)
        directives.append(
            Balance(
                meta=new_metadata(row['File'], 1),
                date=row['Date'].date() + datetime.timedelta(days=1),
                account=self.account,
                amount=Amount(amount, 'GBP'),
                tolerance=None,
                diff_amount=None,
            ))
    return directives
