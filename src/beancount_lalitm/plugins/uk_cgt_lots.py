"""Plugin for UK Capital Gains Tax lot matching using Section 104 pooling.

UK CGT rules require shares to be matched using the Section 104 "pooling"
method, where all shares of the same class are treated as a single pool
with an average cost basis.

This plugin:
1. Tracks Section 104 pools for each security
2. Matches sells against the pool using average cost
3. Calculates capital gains in GBP (required for UK tax)
4. Supports both taxable (GIA) and tax-free (ISA) accounts

Usage in beancount:
  plugin "plugins.uk_cgt_lots" "
    accounts:
      - name: Lalit:UK:AJ-Bell:GIA
        taxable: true
      - name: Lalit:UK:AJ-Bell:ISA
        taxable: false
  "
"""
from beancount.core.data import Cost, Entries, Transaction, Posting, Amount, Directive
from beancount.core import convert
from beancount.core import prices
from dataclasses import dataclass
import collections
from datetime import timedelta, datetime, date
from decimal import Decimal
import sys
from typing import Callable
from typing import Any
import yaml

from beancount_lalitm.importers.account_lookup import AccountOracle

__plugins__ = ['uk_cgt_lots']

ZERO = Decimal('0')


@dataclass
class CgtAccount:
  name: str
  oracle: AccountOracle
  taxable: bool
  section_104_suffix: str


@dataclass
class Match:
  units: Decimal
  cost: Cost
  gbp_allowable_cost: Decimal


class GbpConverter:

  def __init__(self, entries: list[Directive]):
    self.price_map = prices.build_price_map(entries)

  def convert_to_gbp(
      self,
      date: date,
      units: Decimal,
      price: Amount,
  ) -> Decimal:
    assert price.number
    amount = Amount(units * price.number, price.currency)
    out = convert.convert_amount(amount, 'GBP', self.price_map, date).number
    assert out
    return out.quantize(Decimal('0.0001'))


@dataclass
class MatchedTransaction:
  txn: Transaction
  posting: Posting
  matches: list[Match]
  account: CgtAccount

  def unmatched_units(self) -> Decimal:
    posting_units = self.posting.units.number
    matched_units = sum(x.units for x in self.matches)
    assert posting_units
    return posting_units + matched_units

  def capital_gains(self) -> Decimal:
    p = self.posting
    assert p.price and p.price.number
    assert p.units.number and p.units.number < ZERO
    res = (s.units * -s.cost.number for s in self.matches)
    return (p.price.number * p.units.number - sum(res, ZERO)).quantize(
        Decimal('0.0001'))

  def gbp_capital_gains(
      self,
      converter: GbpConverter,
  ) -> list[Decimal]:
    p = self.posting
    assert p.price and p.price.number
    assert p.units.number and self.is_sell()
    return [(converter.convert_to_gbp(self.txn.date, m.units, p.price) -
             m.gbp_allowable_cost).quantize(Decimal('0.0001'))
            for m in self.matches]

  def is_buy(self) -> bool:
    assert self.posting.units and self.posting.units.number
    return self.posting.units.number > ZERO

  def is_sell(self) -> bool:
    assert self.posting.units and self.posting.units.number
    return self.posting.units.number < ZERO


@dataclass
class Section104Holding:
  date: date
  units: Decimal
  average_cost: Decimal
  average_cost_currency: str
  total_allowable_cost_gbp: Decimal


def find_non_section_buys_for_sell(
    s: MatchedTransaction,
    buys: list[MatchedTransaction],
    fn: Callable[[datetime, datetime], bool],
    converter: GbpConverter,
):
  for b in buys:
    if s.posting.units.currency != b.posting.units.currency:
      continue

    if s.account.section_104_suffix != b.account.section_104_suffix:
      continue

    b_units = b.unmatched_units()
    assert b_units >= ZERO
    if b_units == ZERO:
      continue

    if not fn(s.txn.date, b.txn.date):
      continue

    s_units = s.unmatched_units()
    assert s_units < ZERO

    taken_units = min(s_units.copy_abs(), b_units)

    b_price = b.posting.price
    assert b_price and b_price.number
    b_gbp = converter.convert_to_gbp(b.txn.date, taken_units, b_price)

    s_price = s.posting.price
    assert s_price and s_price.number
    s_gbp = converter.convert_to_gbp(s.txn.date, taken_units, s_price)

    cost = Cost(b_price.number, b_price.currency, b.txn.date, None)
    s.matches.append(Match(taken_units, cost, b_gbp))
    b.matches.append(Match(-taken_units, cost, s_gbp))

    assert s.unmatched_units() == s_units + taken_units
    if s_units + taken_units == ZERO:
      return


def same_day_rule(s: datetime, b: datetime) -> bool:
  return s == b


def thirty_day_rule(s: datetime, b: datetime) -> bool:
  return s < b and b <= s + timedelta(days=30)


def match_to_section(
    t: MatchedTransaction,
    section_104_holdings: dict[tuple[str, str], Section104Holding],
    converter: GbpConverter,
):
  unmatched_units = t.unmatched_units()
  if unmatched_units == ZERO:
    return

  price = t.posting.price
  assert price and price.number

  symbol = t.posting.units.currency
  holding = section_104_holdings.setdefault(
      (symbol, t.account.section_104_suffix),
      Section104Holding(t.txn.date, ZERO, ZERO, price.currency, ZERO))

  assert holding.units >= ZERO
  assert holding.average_cost_currency == price.currency

  if holding.units == ZERO:
    assert abs(holding.total_allowable_cost_gbp) < Decimal('1e-12')
    holding.date = t.txn.date
    holding.average_cost = ZERO

  if t.is_sell():
    if holding.units < -unmatched_units:
      print(t, file=sys.stderr)
      print(symbol, file=sys.stderr)
      print(holding, file=sys.stderr)
      print(-unmatched_units, file=sys.stderr)
      assert False
    allowable_cost_gbp = holding.total_allowable_cost_gbp / holding.units * -unmatched_units
    holding.total_allowable_cost_gbp -= allowable_cost_gbp

    cost = Cost(
        holding.average_cost,
        holding.average_cost_currency,
        holding.date,
        'Section-104 ' + t.account.section_104_suffix,
    )
    match = Match(
        -unmatched_units,
        cost,
        allowable_cost_gbp.quantize(Decimal('0.0001')),
    )
    t.matches.append(match)
    holding.units += unmatched_units

    assert holding.units >= ZERO
    return

  assert t.is_buy()

  units_before = holding.units
  assert units_before >= ZERO

  average_cost_before = holding.average_cost
  total_cost_before = average_cost_before * units_before
  total_cost_change = price.number * unmatched_units
  total_cost_after = total_cost_before + total_cost_change

  allowable_cost_gbp = converter.convert_to_gbp(t.txn.date, unmatched_units,
                                                price)

  holding.units += unmatched_units
  holding.average_cost = total_cost_after / holding.units
  holding.total_allowable_cost_gbp += allowable_cost_gbp
  assert holding.units >= ZERO

  cost = Cost(holding.average_cost, holding.average_cost_currency, holding.date,
              'Section-104 ' + t.account.section_104_suffix)
  t.matches.append(Match(-unmatched_units, cost, allowable_cost_gbp))

  if units_before == ZERO or average_cost_before == holding.average_cost:
    return

  t.txn.postings.extend([
      Posting(
          t.posting.account,
          Amount(-units_before, t.posting.units.currency),
          Cost(average_cost_before, holding.average_cost_currency, holding.date,
               'Section-104 ' + t.account.section_104_suffix),
          None,
          None,
          dict(uk_cgt_lots_type='cost-basis-adjustment'),
      ),
      Posting(
          t.posting.account,
          Amount(units_before, t.posting.units.currency),
          Cost(holding.average_cost, holding.average_cost_currency,
               holding.date, 'Section-104 ' + t.account.section_104_suffix),
          None,
          None,
          dict(uk_cgt_lots_type='cost-basis-adjustment'),
      ),
  ])


def uk_cgt_lots(entries: Entries, _: dict, plugin_config: str):
  config: dict = yaml.safe_load(plugin_config)

  accounts = [
      CgtAccount(
          name=x['name'],
          oracle=AccountOracle(x['name'], entries),
          taxable=x.get('taxable', True),
          section_104_suffix='Taxable'
          if x.get('taxable', True) else x['name'].replace(':', '-'),
      ) for x in config['accounts']
  ]

  errors: list[str] = []
  buys: list[MatchedTransaction] = []
  sells: list[MatchedTransaction] = []
  for entry in entries:
    if not isinstance(entry, Transaction):
      continue
    for posting in entry.postings:
      assert isinstance(posting, Posting)
      if not posting.account.startswith('Assets'):
        continue
      if posting.account.endswith('Cash'):
        continue
      account = next((a for a in accounts if a.name in posting.account), None)
      if not account:
        continue
      assert posting.units.number and posting.units.number != ZERO
      if posting.units.number > ZERO:
        buys.append(MatchedTransaction(entry, posting, [], account))
      else:
        sells.append(MatchedTransaction(entry, posting, [], account))
      entry.postings.remove(posting)
      break

  converter = GbpConverter(entries)

  # Same day sales
  for s in sells:
    assert s.unmatched_units() < ZERO
    find_non_section_buys_for_sell(s, buys, same_day_rule, converter)

  # Thirty day sales
  for s in sells:
    assert s.unmatched_units() <= ZERO
    if s.unmatched_units() == ZERO:
      continue
    find_non_section_buys_for_sell(s, buys, thirty_day_rule, converter)

  # Section 104 holdings
  all = sorted(buys + sells, key=lambda x: x.txn.date)
  section_104_holdings: dict[tuple[str, str],
                             Section104Holding] = collections.defaultdict()
  for t in all:
    match_to_section(t, section_104_holdings, converter)
    assert t.unmatched_units() == ZERO

    postings = list(t.txn.postings)
    t.txn.postings.clear()
    t.txn.postings.extend([
        Posting(
            t.posting.account,
            Amount(-c.units, t.posting.units.currency),
            c.cost,
            t.posting.price,
            t.posting.flag,
            t.posting.meta,
        ) for c in t.matches
    ])
    t.txn.postings.extend(postings)
    assert t.posting.meta
    if t.posting.meta.get('uk_cgt_lots_manual'):
      continue

    if t.is_buy():
      continue

    assert t.is_sell()
    price = t.posting.price
    assert price

    cg = t.capital_gains()
    if cg == ZERO:
      continue

    name = t.posting.account.replace('Assets:', '')
    t.txn.postings.extend([
        Posting(
            f'Revenues:{name}:Capital-Gains',
            Amount(cg, price.currency),
            None,
            None,
            None,
            None,
        ),
    ])

    if t.account.taxable:
      for gbp_cg in t.gbp_capital_gains(converter):
        t.txn.postings.extend([
            Posting(
                'Equity:Taxable-Capital-Gains',
                Amount(gbp_cg, "CGT-GBP"),
                None,
                None,
                None,
                None,
            ),
            Posting(
                'Equity:Taxable-Capital-Gains-Placeholder',
                Amount(-gbp_cg, "CGT-GBP"),
                None,
                None,
                None,
                None,
            ),
        ])

  return entries, errors
