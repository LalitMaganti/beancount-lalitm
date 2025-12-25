# beancount-lalitm

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

### Investment Platforms

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `IbImporter` | Interactive Brokers | Flex Query XML |
| `SchwabEacImporter` | Schwab Equity Award Center | Text (PDF converted) |
| `VanguardImporter` | Vanguard UK | Excel |
| `IgImporter` | IG Trading | Text (PDF converted) |
| `AjTransactionsImporter` | AJ Bell transactions | PDF |
| `AjCashImporter` | AJ Bell cash history | CSV |
| `AvivaPensionImporter` | Aviva pension | Text (PDF converted) |

### Banks

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `HsbcImporter` | HSBC UK current account | Text (PDF converted) |
| `HsbcUkCcImporter` | HSBC UK credit card | JSON |
| `HsbcUsCcImporter` | HSBC US credit card | JSON |
| `HsbcUsCheckingImporter` | HSBC US checking | Text (PDF converted) |

### Payroll

| Importer | Description | Input Format |
|----------|-------------|--------------|
| `GooglePayslipImporter` | Google UK payslips | Text (PDF converted) |

## Plugins

### ancillary_accounts

Auto-creates companion accounts for investment securities (commissions, dividends, capital gains, withholding tax).

```beancount
plugin "beancount_tools.plugins.ancillary_accounts"

2024-01-01 open Assets:Broker:AAPL  AAPL
  ancillary_commission_currency: USD
  ancillary_distribution_currency: USD
  ancillary_capital_gains_currency: USD
```

### stock_split

Adjusts historical transactions for stock splits.

```beancount
plugin "beancount_tools.plugins.stock_split" "
  splits:
    - symbol: GOOG
      date: 2022-07-15
      ratio: 20
"
```

### uk_cgt_lots

UK Capital Gains Tax lot matching using Section 104 pooling.

```beancount
plugin "beancount_tools.plugins.uk_cgt_lots" "
  accounts:
    - name: Person:UK:Broker:GIA
      taxable: true
    - name: Person:UK:Broker:ISA
      taxable: false
"
```

## License

Apache 2.0 - see [LICENSE](LICENSE) for details.
