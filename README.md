# beancount-lalitm

[![PyPI](https://img.shields.io/pypi/v/beancount-lalitm)](https://pypi.org/project/beancount-lalitm/)

Importers and plugins for [Beancount](https://beancount.github.io/) plain-text accounting.

> **Disclaimer:** I am not a tax professional or financial advisor. This code is provided as-is for personal use. The `uk_cgt_lots` plugin in particular implements my understanding of UK Capital Gains Tax rules, which may be incomplete or incorrect. Use at your own risk.

## Installation

```bash
pip install beancount-lalitm

# With optional dependencies for specific importers
pip install beancount-lalitm[ib]      # Interactive Brokers (XML)
pip install beancount-lalitm[pdf]     # PDF-based importers
pip install beancount-lalitm[excel]   # Excel-based importers
pip install beancount-lalitm[all]     # All optional dependencies
```

## Importers

### Investment Accounts (Fully Automated)

Investment importers can run directly via beangulp since no categorization is needed.

Create an `import.py`:

```python
#!/usr/bin/env python3
"""Beancount import configuration for investments."""
import beangulp
from beancount import loader
from beancount_lalitm.importers.account_lookup import AccountOracle
from beancount_lalitm.importers.ib import IbImporter

entries, errors, options = loader.load_file('main.beancount')

ib_oracle = AccountOracle(
    account='Lalit:US:IB:Brokerage',
    entries=entries,
    transfers_account='Assets:Lalit:US:IB:Transfers',
)

CONFIG = [
    IbImporter(account_currency='USD', account_oracle=ib_oracle),
]

if __name__ == '__main__':
    beangulp.Ingest(CONFIG)()
```

Run directly with beangulp:

```bash
python import.py extract ~/Downloads/ib-flex-query.xml >> investments.beancount
```

### Bank Accounts (Semi-Automated)

Bank and credit card importers require categorization. Use [beancount-import](https://github.com/jbms/beancount-import) for a web UI that learns from your previous choices.

```python
#!/usr/bin/env python3
"""Beancount import configuration for banks."""
from beancount_lalitm.importers.hsbc import HsbcImporter
from beancount_lalitm.importers.hsbc_uk_cc import HsbcUkCcImporter

CONFIG = [
    HsbcImporter(account='Assets:Lalit:UK:HSBC:Current'),
    HsbcUkCcImporter(account='Liabilities:Lalit:UK:HSBC:CreditCard'),
]
```

Run the beancount-import web UI:

```bash
python -m beancount_import.webserver \
    --journal journal.beancount \
    --ignored_path ignored.beancount \
    --account_filter '^Assets:Lalit:UK:HSBC'
```

### Available Importers

#### Investment Platforms

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `IbImporter` | Interactive Brokers | Flex Query XML |
| `SchwabEacImporter` | Schwab Equity Award Center | Text (PDF converted) |
| `VanguardImporter` | Vanguard UK | Excel |
| `IgImporter` | IG Trading | Text (PDF converted) |
| `AjTransactionsImporter` | AJ Bell transactions | PDF |
| `AjCashImporter` | AJ Bell cash history | CSV |
| `AvivaPensionImporter` | Aviva pension | Text (PDF converted) |

#### Banks

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `HsbcImporter` | HSBC UK current account | Text (PDF converted) |
| `HsbcUkCcImporter` | HSBC UK credit card | JSON |
| `HsbcUsCcImporter` | HSBC US credit card | JSON |
| `HsbcUsCheckingImporter` | HSBC US checking | Text (PDF converted) |

#### Payroll

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `GooglePayslipImporter` | Google UK payslips | Text (PDF converted) |

## Plugins

Add plugins to your beancount file with the `plugin` directive.

### ancillary_accounts

Auto-creates companion accounts for investment securities (commissions, dividends, capital gains, withholding tax).

```beancount
plugin "beancount_lalitm.plugins.ancillary_accounts"

2024-01-01 open Assets:Broker:AAPL  AAPL
  ancillary_commission_currency: USD
  ancillary_distribution_currency: USD
  ancillary_capital_gains_currency: USD
```

### stock_split

Adjusts historical transactions for stock splits.

```beancount
plugin "beancount_lalitm.plugins.stock_split" "
  splits:
    - symbol: GOOG
      date: 2022-07-15
      ratio: 20
"
```

### uk_cgt_lots

UK Capital Gains Tax lot matching using Section 104 pooling.

```beancount
plugin "beancount_lalitm.plugins.uk_cgt_lots" "
  accounts:
    - name: Person:UK:Broker:GIA
      taxable: true
    - name: Person:UK:Broker:ISA
      taxable: false
"
```

## License

Apache 2.0 - see [LICENSE](LICENSE) for details.
