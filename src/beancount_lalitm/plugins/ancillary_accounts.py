"""Plugin to auto-create ancillary accounts for investment securities.

When an Open directive has metadata like `ancillary_commission_currency: USD`,
this plugin automatically creates companion accounts for:
- Commission expenses
- Dividend/distribution income
- Capital gains
- Withholding tax

These accounts are created with the same date as the main account open,
and are automatically closed when the main account is closed.

Usage in beancount:
  plugin "plugins.ancillary_accounts"

Example:
  2024-01-01 open Assets:Lalit:US:IB:Brokerage:AAPL  AAPL
    ancillary_commission_currency: USD
    ancillary_distribution_currency: USD
    ancillary_capital_gains_currency: USD
    ancillary_withholding_tax_currency: USD

This will also create:
  - Expenses:Lalit:US:IB:Brokerage:AAPL:Commissions
  - Revenues:Lalit:US:IB:Brokerage:AAPL:Dividends
  - Revenues:Lalit:US:IB:Brokerage:AAPL:Capital-Gains
  - Expenses:Lalit:US:IB:Brokerage:AAPL:Withholding-Tax
"""
from typing import Callable
from beancount.core import account
from beancount.core.data import Close
from beancount.core.data import Directive
from beancount.core.data import Entries
from beancount.core.data import new_metadata
from beancount.core.data import Open

from beancount_lalitm.importers.account_lookup import AccountOracle

__plugins__ = ['ancillary_accounts']


def add(
    entry: Directive,
    key: str,
    account: Callable[[], str],
    new_entries: Entries,
    to_close_accounts: list[str],
):
  currency: str | None = entry.meta.get(key)
  if not currency:
    return
  open = Open(
      date=entry.date,
      meta=new_metadata('foo', 1),
      account=account(),
      currencies=[currency],
      booking=None,
  )
  new_entries.append(open)
  to_close_accounts.append(account())


def ancillary_accounts(entries: Entries, _: dict, plugin_config: str):
  accounts: dict[str, list[str]] = {}
  errors: list[str] = []
  new_entries: Entries = []
  for entry in entries:
    new_entries.append(entry)

    if isinstance(entry, Open):
      to_close_accounts = []
      if entry.account in accounts:
        errors.append('Duplicate open directive not allowed')
        return [], errors

      acc_name = str(account.parent(account.sans_root(entry.account)))
      symbol = str(account.leaf(entry.account))
      account_oracle = AccountOracle(acc_name, entries)
      add(
          entry,
          'ancillary_commission_currency',
          lambda: account_oracle.commission_account(symbol),
          new_entries,
          to_close_accounts,
      )
      add(
          entry,
          'ancillary_distribution_currency',
          lambda: account_oracle.distribution_account(symbol),
          new_entries,
          to_close_accounts,
      )
      add(
          entry,
          'ancillary_capital_gains_currency',
          lambda: account_oracle.capital_gains_account(symbol),
          new_entries,
          to_close_accounts,
      )
      add(
          entry,
          'ancillary_withholding_tax_currency',
          lambda: account_oracle.withholding_taxes_account(symbol),
          new_entries,
          to_close_accounts,
      )
      accounts[entry.account] = to_close_accounts

    if isinstance(entry, Close):
      to_close_accounts = accounts.get(entry.account)
      if not to_close_accounts:
        continue

      for a in to_close_accounts:
        new_entries.append(Close(meta=entry.meta, date=entry.date, account=a))
      del accounts[entry.account]

  return new_entries, errors
