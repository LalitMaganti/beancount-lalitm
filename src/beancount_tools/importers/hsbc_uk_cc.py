"""Importer for HSBC UK credit card statements.

Parses JSON-formatted credit card statement data to extract:
- All transactions with dates and amounts
- Balance assertions at statement date
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
import json


class HsbcUkCcImporter(importer.ImporterProtocol):
  """Importer for HSBC UK credit card statements (JSON format).

  Args:
    account: The beancount account path for this credit card.
  """

  def __init__(self, account: str):
    self.account = account

  def identify(self, file: _FileMemo):
    return file.name.endswith('.json')

  def extract(self, file: _FileMemo,
              existing_entries: Entries | None) -> list[Directive]:
    p = json.loads(file.contents())

    raw_stmt_date, balance = None, None
    directives: list[Directive] = []
    for s in (
        [k['text'] for k in j if k['text']] for i in p for j in i['data']):
      raw_res = ' '.join(s)
      res = raw_res.split(' ')
      try:
        date = datetime.datetime.strptime(' '.join(res[0:3]), '%d %b %y').date()
        _ = datetime.datetime.strptime(' '.join(res[3:6]), '%d %b %y').date()
      except ValueError:
        if s and s[0].startswith('New Balance') and not balance:
          balance = s[0]
        if s and s[0].startswith('Statement Date') and not raw_stmt_date:
          raw_stmt_date = s[0]
        continue

      details = ' '.join(x for x in res[6:-1] if x)
      raw_units = res[-1].replace(',', '')
      negative = Decimal('-1') if raw_units.endswith('CR') else Decimal('1')
      units = raw_units.replace('CR', '')
      directives.append(
          Transaction(
              meta=new_metadata(file.name, 1),
              date=date,
              flag='*',
              payee=None,
              narration=details,
              tags=set(),
              links=set(),
              postings=[
                  Posting(
                      account=self.account,
                      units=Amount(negative * -Decimal(units), 'GBP'),
                      cost=None,
                      price=None,
                      flag=None,
                      meta=None,
                  ),
              ],
          ))

    assert raw_stmt_date and balance
    stmt_date = datetime.datetime.strptime(raw_stmt_date,
                                           'Statement Date %d %B %Y')
    balance_str = balance.split(' ')[-1].replace(',', '')
    cr = Decimal('1') if balance_str.endswith('CR') else Decimal('-1')
    directives.append(
        Balance(
            meta=new_metadata(file.name, 1),
            date=stmt_date.date() + datetime.timedelta(days=1),
            amount=Amount(cr * Decimal(balance_str.replace('CR', '')), 'GBP'),
            account=self.account,
            diff_amount=None,
            tolerance=None,
        ))
    return directives
