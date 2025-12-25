"""Importer for Google UK payslips.

Parses text-converted PDF payslips to extract:
- Gross salary and salary supplements
- Pension contributions
- Bonuses (peer, spot, annual)
- Tax deductions (PAYE, NI)
- Stock withholding credits
- Student loan deductions
- Net pay
"""
from beancount.core.data import Amount
from beancount.core.data import Directive
from beancount.core.data import Entries
from beancount.core.data import Posting
from beancount.core.data import Transaction
from beancount.core.data import new_metadata
from beangulp import importer
from beangulp.cache import _FileMemo
import datetime
from decimal import Decimal
import io
import pandas as pd
import sys


def new_posting(postings: list[Posting], account: str, amount: Decimal):
  if amount != 0:
    postings.append(
        Posting(
            account=account,
            units=Amount(amount, 'GBP'),
            cost=None,
            price=None,
            flag=None,
            meta=None,
        ))


def find(lines: list[str], pattern: str) -> int:
  return next(i for i, line in enumerate(lines) if pattern in line)


class GooglePayslipImporter(importer.ImporterProtocol):
  """Importer for Google UK payslips (text format).

  Handles both old and new payslip formats. All account names are
  configurable to allow customization for different accounting structures.

  Args:
    gross_salary_revenue_account: Account for gross salary income.
    pension_transfer_account: Account for pension contributions.
    peer_bonus_revenue_account: Account for peer bonus income.
    spot_bonus_revenue_account: Account for spot bonus income.
    annual_bonus_revenue_account: Account for annual bonus income.
    income_tax_account: Account for PAYE tax deductions.
    ni_account: Account for National Insurance deductions.
    payslip_transfer_account: Account for net pay transfers.
    stock_withholding_revenue_account: Account for stock withholding credits.
    student_loan_expense_account: Account for student loan deductions.
    ee_gia_transfer_account: Account for Employee Equity GIA fund transfers.
    commuter_loan_transfer_account: Account for commuter loan transfers.
    leave_purchase_expense_account: Account for leave purchase deductions.
  """

  def __init__(
      self,
      gross_salary_revenue_account: str,
      pension_transfer_account: str,
      peer_bonus_revenue_account: str,
      spot_bonus_revenue_account: str,
      annual_bonus_revenue_account: str,
      income_tax_account: str,
      ni_account: str,
      payslip_transfer_account: str,
      stock_withholding_revenue_account: str,
      student_loan_expense_account: str,
      ee_gia_transfer_account: str,
      commuter_loan_transfer_account: str,
      leave_purchase_expense_account: str,
  ):
    self.gross_salary_revenue_account = gross_salary_revenue_account
    self.pension_transfer_account = pension_transfer_account
    self.peer_bonus_revenue_account = peer_bonus_revenue_account
    self.annual_bonus_revenue_account = annual_bonus_revenue_account
    self.spot_bonus_revenue_account = spot_bonus_revenue_account
    self.income_tax_account = income_tax_account
    self.ni_account = ni_account
    self.payslip_transfer_account = payslip_transfer_account
    self.stock_withholding_revenue_account = stock_withholding_revenue_account
    self.student_loan_expense_account = student_loan_expense_account
    self.ee_gia_transfer_account = ee_gia_transfer_account
    self.commuter_loan_transfer_account = commuter_loan_transfer_account
    self.leave_purchase_expense_account = leave_purchase_expense_account

  def identify(self, file: _FileMemo):
    return 'Payslip' in file.name and '.txt' in file.name

  def extract(self,
              file: _FileMemo,
              existing_entries: Entries | None = None) -> list[Directive]:
    x = self.pdf_to_table(file.contents())
    return [x] if x else []

  def pdf_to_table_old(self, lines: list[str]) -> Transaction:
    date_idx = find(lines, ' M ')
    date_str = lines[date_idx].split(' ')[-1]
    date = datetime.datetime.strptime(date_str, '%d/%m/%Y').date()

    transaction = Transaction(
        meta=new_metadata('foo', 1),
        date=date,
        flag='*',
        payee=None,
        narration='PAYSLIP',
        tags=set(['payslip']),
        links=set(),
        postings=[],
    )
    postings: list[Posting] = transaction.postings

    taxable_start = find(lines, 'GROSS PAY')
    taxable_end = find(lines, 'TOTAL PAY')
    adjustments = lines[taxable_start + 2:taxable_end]

    gross_amount_idx = lines[taxable_start + 1].find('Amount(£)')
    deductions_amount_idx = lines[taxable_start + 1].find(
        'Amount(£)', gross_amount_idx + 1)

    gross = pd.read_fwf(
        io.StringIO('\n'.join(adjustments)),
        colspecs=[
            (0, gross_amount_idx - 2),
            (gross_amount_idx - 2, gross_amount_idx + 10),
        ],
        names=['Description', 'Current'],
        dtype=str,
    )
    for r in gross.to_dict(orient='records'):
      current = Decimal(r['Current'].replace(',', ''))
      if r['Description'] == 'Salary':
        new_posting(postings, self.gross_salary_revenue_account, -current)
        continue
      if r['Description'] == 'ER Sal Supp':
        new_posting(postings, self.gross_salary_revenue_account, -current)
        continue
      if r['Description'] == 'SS Pension':
        new_posting(postings, self.pension_transfer_account, -current)
        continue
      if r['Description'] == 'Spot Gross':
        new_posting(postings, self.spot_bonus_revenue_account, -current)
        continue
      if r['Description'] == 'Peer Bonus':
        new_posting(postings, self.peer_bonus_revenue_account, -current)
        continue
      if r['Description'] == 'Company Bon':
        new_posting(postings, self.annual_bonus_revenue_account, -current)
        continue
      if r['Description'] == 'Promo Bonus':
        new_posting(postings, self.gross_salary_revenue_account, -current)
        continue
      if r['Description'] == 'Comm Tck Ln':
        new_posting(postings, self.commuter_loan_transfer_account, -current)
        continue
      if r['Description'] == 'Leave Purch':
        new_posting(postings, self.leave_purchase_expense_account, -current)
        continue
      if r['Description'] == 'GSU Income':
        # Tracked by Schwab
        continue
      print(r, file=sys.stderr)
      raise Exception('Gross')

    deductions = pd.read_fwf(
        io.StringIO('\n'.join(adjustments)),
        colspecs=[
            (gross_amount_idx + 10, deductions_amount_idx - 2),
            (deductions_amount_idx - 2, deductions_amount_idx + 10),
        ],
        names=['Description', 'Current'],
        dtype=str,
    )
    for r in deductions.to_dict(orient='records'):
      current = Decimal(r['Current'].replace(',', ''))
      if r['Description'] == 'P.A.Y.E.':
        new_posting(postings, self.income_tax_account, -current)
        continue
      if r['Description'] == 'Emp Rec prv':
        new_posting(postings, self.income_tax_account, -current)
        continue
      if r['Description'] == 'N.I.':
        new_posting(postings, self.ni_account, -current)
        continue
      if r['Description'] == 'GSU Refund':
        new_posting(postings, self.stock_withholding_revenue_account, -current)
        continue
      if r['Description'] == 'Std. loan':
        new_posting(postings, self.student_loan_expense_account, -current)
        continue
      if r['Description'] == 'EE GIA Fund':
        new_posting(postings, self.ee_gia_transfer_account, -current)
        continue
      if r['Description'] == 'Comm Tck Ded':
        new_posting(postings, self.commuter_loan_transfer_account, -current)
        continue
      if r['Description'] == 'GSU Deduct':
        # Tracked by Schwab
        continue
      if r['Description'] == '{Medical BIK':
        # Not directly taxed
        continue
      if r['Description'] == '{Dental BIK':
        # Not directly taxed
        continue
      print(r, file=sys.stderr)
      raise Exception('Deductions')

    net_pay = lines[find(lines, 'NET PAY ')].replace('NET PAY', '').strip()
    new_posting(postings, self.payslip_transfer_account,
                Decimal(net_pay.replace(',', '').replace('GBP', '').strip()))

    return transaction

  def pdf_to_table_new(self, lines: list[str]) -> Transaction:
    date_idx = find(lines, 'Date of Payment')
    date_str = lines[date_idx].replace('Date of Payment', '').strip()
    date = datetime.datetime.strptime(date_str, '%d %B %Y').date()

    transaction = Transaction(
        meta=new_metadata('foo', 1),
        date=date,
        flag='*',
        payee=None,
        narration='PAYSLIP',
        tags=set(['payslip']),
        links=set(),
        postings=[],
    )
    postings: list[Posting] = transaction.postings

    taxable_start = find(lines, 'Taxable Earnings')
    taxable_end = find(lines, 'Total Taxable Earnings')
    taxable = lines[taxable_start + 1:taxable_end]

    type_idx = lines[taxable_start].find('Earning type')
    prior_idx = lines[taxable_start].find('Prior period')
    current_idx = lines[taxable_start].find('Current')
    ytd_idx = lines[taxable_start].find('YTD')
    df = pd.read_fwf(
        io.StringIO('\n'.join(taxable)),
        colspecs=[
            (0, type_idx),
            (type_idx, prior_idx),
            (prior_idx, current_idx - 2),
            (current_idx - 2, current_idx + 8),
            (current_idx + 8, ytd_idx + 3),
        ],
        names=['Description', 'Type', 'Prior', 'Current', 'YTD'],
        dtype=str,
    )
    for r in df.to_dict(orient='records'):
      prior = Decimal(r['Prior'].replace(',', ''))
      current = Decimal(r['Current'].replace(',', ''))
      if r['Description'] == 'Pension Sac EE':
        new_posting(postings, self.pension_transfer_account, -current)
        continue
      if r['Description'] == 'Gross Salary Monthly':
        new_posting(postings, self.gross_salary_revenue_account, -current)
        continue
      if r['Description'] == 'Peer Bonus':
        new_posting(postings, self.peer_bonus_revenue_account, -current)
        new_posting(postings, self.peer_bonus_revenue_account, -prior)
        continue
      if r['Description'] == 'Annual Bonus Gross' or r[
          'Description'] == 'BONUS_GROSS':
        new_posting(postings, self.annual_bonus_revenue_account, -current)
        continue
      if r['Description'] == 'Spot Bonus Gross':
        new_posting(postings, self.spot_bonus_revenue_account, -current)
        new_posting(postings, self.spot_bonus_revenue_account, -prior)
        continue
      print(r, file=sys.stderr)
      raise Exception('Taxable')

    try:
      non_taxable_start = find(lines, 'Non Taxable Earnings')
      non_taxable_end = find(lines, 'Total Non Taxable Earnings')
      non_taxable = lines[non_taxable_start + 1:non_taxable_end]
      type_idx = lines[non_taxable_start].find('Earning type')
      prior_idx = lines[non_taxable_start].find('Prior period')
      current_idx = lines[non_taxable_start].find('Current')
      ytd_idx = lines[non_taxable_start].find('YTD')
      df = pd.read_fwf(
          io.StringIO('\n'.join(non_taxable)),
          colspecs=[
              (0, type_idx),
              (type_idx, prior_idx),
              (prior_idx, current_idx - 2),
              (current_idx - 2, current_idx + 8),
              (current_idx + 8, ytd_idx + 3),
          ],
          names=['Description', 'Type', 'Prior', 'Current', 'YTD'],
          dtype=str,
      )
    except StopIteration:
      df = pd.DataFrame()

    for r in df.to_dict(orient='records'):
      prior = Decimal(r['Prior'].replace(',', ''))
      current = Decimal(r['Current'].replace(',', ''))
      if r['Description'] == 'MSSB Withholding Credit':
        new_posting(postings, self.stock_withholding_revenue_account, -current)
        new_posting(postings, self.stock_withholding_revenue_account, -prior)
        continue
      if r['Description'] == 'Claim to be recovered':
        new_posting(postings, self.income_tax_account, -current)
        new_posting(postings, self.income_tax_account, -prior)
        continue
      print(r, file=sys.stderr)
      raise Exception('Non-taxable')

    deductions_start = find(lines, 'Statutory Deductions:')
    deductions_end = find(lines, 'Total Statutory Deductions')
    deductions = lines[deductions_start + 1:deductions_end]

    current_idx = lines[deductions_start].find('Current')
    ytd_idx = lines[deductions_start].find('YTD')
    df = pd.read_fwf(
        io.StringIO('\n'.join(deductions)),
        colspecs=[
            (0, current_idx - 4),
            (current_idx - 4, current_idx + 8),
            (current_idx + 8, ytd_idx + 3),
        ],
        names=['Description', 'Current', 'YTD'],
        dtype=str,
    )
    for r in df.to_dict(orient='records'):
      current = Decimal(r['Current'].replace(',', ''))
      if r['Description'] == 'Tax':
        new_posting(postings, self.income_tax_account, current)
        continue
      if r['Description'] == 'Employee NI':
        new_posting(postings, self.ni_account, current)
        continue
      print(r, file=sys.stderr)
      raise Exception('Deductions')

    net_pay = lines[find(lines, 'Net Pay   ')].replace('Net Pay', '').strip()
    new_posting(postings, self.payslip_transfer_account,
                Decimal(net_pay.replace(',', '').replace('GBP', '').strip()))

    return transaction

  def pdf_to_table(self, contents: str) -> Transaction:
    lines = [l for l in contents.split('\n')]

    if 'PAYSLIP / CONFIDENTIAL' in lines[0]:
      return self.pdf_to_table_new(lines)

    if 'PRIVATE AND CONFIDENTIAL' in lines[0]:
      return self.pdf_to_table_old(lines)
