"""Importer for HSBC US credit card statements.

Parses JSON-formatted credit card statement data to extract
transactions with dates and amounts in USD.
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
import datetime
import json


class HsbcUsCcImporter(importer.ImporterProtocol):
  """Importer for HSBC US credit card statements (JSON format).

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

    directives = []
    for s in ([k['text'] for k in j] for i in p for j in i['data']):
      x = s[0].split(' ')
      if len(x) != 2:
        continue
      try:
        date = datetime.datetime.strptime(x[0], '%m/%d/%y').date()
        _ = datetime.datetime.strptime(x[1], '%m/%d/%y').date()
      except ValueError:
        continue
      if s[-1] == '$0.00':
        continue

      details = ' '.join([x for x in s[1:-1] if x])
      units = s[-1].replace('$', '').replace(',', '')
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
                      units=Amount(-Decimal(units), 'USD'),
                      cost=None,
                      price=None,
                      flag=None,
                      meta=None,
                  ),
              ],
          ))
    return directives
