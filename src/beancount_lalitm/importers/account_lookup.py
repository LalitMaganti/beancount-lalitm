from typing import Optional
from beancount.core.data import Entries, Commodity


class AccountOracle:
  """Generates account names consistently for a given brokerage account.

  Args:
    account: The base account path (e.g., 'Lalit:US:IB:Brokerage').
    entries: Beancount entries to extract commodity distribution types from.
    transfers_account: Optional account for transfers (e.g., internal transfers).
    stock_revenue_account: Optional account for stock compensation revenue.
  """

  def __init__(
      self,
      account: str,
      entries: Entries,
      transfers_account: Optional[str] = None,
      stock_revenue_account: Optional[str] = None,
  ):
    self._distribution_type: dict[str, str] = {}
    for entry in entries:
      if isinstance(entry, Commodity):
        self._distribution_type[entry.currency] = entry.meta.get(
            'distribution_type', 'Dividends')

    self._assets_account = 'Assets:' + account
    self._revenues_account = 'Revenues:' + account
    self._expenses_account = 'Expenses:' + account
    self._transfers_account = transfers_account
    self._stock_revenue_account = stock_revenue_account

  def cash_account(self) -> str:
    return self._assets_account + ':Cash'

  def asset_account(self, symbol: str) -> str:
    return self._assets_account + ':' + symbol

  def distribution_account(self, symbol: str) -> str:
    return self._revenues_account + ':' + symbol + ':' + self._distribution_type[
        symbol]

  def capital_gains_account(self, symbol: str) -> str:
    return self._revenues_account + ':' + symbol + ':' + 'Capital-Gains'

  def account_interest_account(self) -> str:
    return self._revenues_account + ':Cash:Interest'

  def account_fees_account(self) -> str:
    return self._expenses_account + ':Cash:Fees'

  def withholding_taxes_account(self, symbol: str) -> str:
    return self._expenses_account + ':' + symbol + ':Withholding-Tax'

  def commission_account(self, symbol: str) -> str:
    return self._expenses_account + ':' + symbol + ':Commissions'

  def transfers_account(self) -> str:
    if self._transfers_account is None:
      raise ValueError('transfers_account not configured in AccountOracle')
    return self._transfers_account

  def stock_revenue_account(self) -> str:
    if self._stock_revenue_account is None:
      raise ValueError('stock_revenue_account not configured in AccountOracle')
    return self._stock_revenue_account
