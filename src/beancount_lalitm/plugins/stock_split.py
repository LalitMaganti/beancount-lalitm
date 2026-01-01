"""Plugin to adjust historical transactions for stock splits.

When a stock split occurs, this plugin retroactively adjusts the units
and prices of all historical transactions before the split date so that
quantities and prices are consistent with post-split values.

Usage in beancount:
  plugin "plugins.stock_split" "
    splits:
      - symbol: GOOG
        date: 2022-07-15
        ratio: 20
  "

This will multiply all GOOG units before 2022-07-15 by 20 and divide
the price by 20, keeping the total value unchanged.
"""
from beancount.core.data import Cost, Entries, Transaction, Posting, Amount, Price
from dataclasses import dataclass
import collections
from datetime import timedelta, datetime, date
from decimal import Decimal
import sys
from typing import Callable
from typing import Any
import yaml

__plugins__ = ['stock_split']

ZERO = Decimal('0')


def stock_split(entries: Entries, _: dict, plugin_config: str):
  config: dict = yaml.safe_load(plugin_config)
  splits: dict[str, Any] = {l['symbol']: l for l in config['splits']}
  errors: list[str] = []
  for entry in entries:
    if not isinstance(entry, Transaction):
      continue
    for posting in entry.postings:
      assert isinstance(posting, Posting)
      if posting.units.currency not in splits:
        continue
      s = splits[posting.units.currency]
      date = s['date']
      assert entry.date != date
      assert not posting.cost and posting.price
      if entry.date > date:
        continue
      assert posting.units.number and posting.price.number
      entry.postings.remove(posting)
      entry.postings.append(
          posting._replace(
              units=Amount(posting.units.number * Decimal(s['ratio']),
                           posting.units.currency),
              price=Amount(posting.price.number / Decimal(s['ratio']),
                           posting.price.currency),
          ))
      break

  return entries, errors
