# Chakki ERP

Mobile-first, bilingual **On-Demand Chakki (Flour Mill) Management & Accounting ERP** built with Django 6, Tailwind CSS 4, HTMX, Alpine.js and Plotly.js.

The application is designed for day-to-day use on **phones and tablets** at a village chakki counter while preserving production-grade accounting controls, inventory movements, customer Udhaar, supplier payables, payroll, machine maintenance and dynamic QR/UPI settlement.

## Stack

- **Backend:** Django 6 / Python 3.12+
- **Database:** PostgreSQL for production; SQLite supported for local evaluation
- **UI:** semantic Django templates + Tailwind CSS 4
- **Component language:** shadcn-style semantic tokens and primitives adapted to server-rendered Django
- **Navigation:** shadcn off-canvas sidebar pattern; always closed by default on phone, tablet and desktop
- **Partial page interactions:** HTMX
- **Client state:** Alpine.js
- **Charts:** Plotly.js with backend-generated JSON
- **Icons:** Lucide
- **Static serving:** WhiteNoise
- **Production WSGI:** Gunicorn
- **Containerization:** Docker / Docker Compose

> shadcn/ui is a React component source system, while this project is intentionally server-rendered Django. The application therefore implements the same shadcn semantic CSS-variable model, visual primitives and off-canvas sidebar interaction without adding a React runtime. This keeps HTMX/Django as the authoritative UI architecture.

## Mobile / tablet UX

The main workflow is optimized for touch use:

- Navigation is **never permanently open**. It starts closed on every page and every screen size.
- The header menu button opens the navigation as a secondary off-canvas sheet.
- Selecting a module closes the sheet immediately.
- Backdrop tap and `Escape` close the sheet.
- Controls use touch-friendly sizing.
- Tables use horizontal overflow rather than breaking the viewport.
- Main content remains full width when the sidebar is closed.
- EN / हिन्दी switching is available in the top bar.
- Light/dark themes use shadcn semantic theme tokens.

## Modules

1. **Dashboard** — HTMX-polled today's grinding weight, net income, expenses, active cash, outstanding Udhaar and pending jobs; Plotly seven-day processing chart.
2. **Customers** — permanent/temporary customers, contact details, village tags, opening balances, smart search and order history.
3. **Grinding** — Intake → Grinding → Ready → Dispatched / Delivered workflow.
4. **Rate Card** — grain/service/Jalan rate matrix with bounded negotiated overrides.
5. **Udhaar** — customer outstanding ledger, receipts and adjustments.
6. **Old Udhaar** — opening-balance tracking and FIFO settlement history.
7. **Accounts** — granular cash book and double-entry ledger.
8. **Inventory** — raw grains, packed atta, oil, Khal/by-products, gunny bags and other stock.
9. **Purchases** — supplier procurement, inventory receipts and payable postings.
10. **Sales** — retail checkout with sales income and COGS posting.
11. **Buyback** — customer by-product/finished-product buyback against processing fees.
12. **Production** — raw input vs output, by-product, process loss and yield.
13. **Wastage** — milling loss, dust and process waste logs.
14. **Utilities** — electricity, fuel, water and other operating costs.
15. **Employees** — worker profile and employment terms.
16. **Attendance** — daily check-in/check-out and attendance status.
17. **Payroll** — workday-driven wage calculation and accounting posting.
18. **Maintenance** — belts, bearings, lubrication, motor work and stone channelling/Takai schedules.
19. **Suppliers** — vendor directory and payable balances.
20. **Reports** — operational reports, Profit & Loss and Trial Balance.
21. **Settings** — owner read-only configuration summary; actual system changes are made only through Django Admin.
22. **Users / Roles** — Owner, Manager, Operator and Accountant RBAC.

## Accounting architecture

Every financial event posts a balanced `JournalEntry` with at least two `LedgerEntry` rows. `LedgerEntry.transactional_balance` stores the running balance in the account's normal balance direction.

Seeded system accounts include:

- Cash Book
- Accounts Receivable (Udhaar)
- Inventory Asset
- Accounts Payable (Suppliers)
- Customer Buyback Payable
- Opening Balance Equity
- Grinding Income
- Retail Sales Income
- Expense: Customer Goodwill/Forgiven
- Cost of Goods Sold
- Utility Expense
- Wage and Payroll Expense
- Maintenance Expense
- General Operating Expense

Posted `JournalEntry` and `LedgerEntry` records are read-only in Django Admin to protect ledger integrity.

### Grinding forgiveness example

For a ₹43 grinding bill, ₹40 paid and ₹3 forgiven:

```text
Dr Accounts Receivable (Udhaar)          ₹40
Dr Expense: Customer Goodwill/Forgiven    ₹3
    Cr Grinding Income                         ₹43

Dr Cash                                   ₹40
    Cr Accounts Receivable (Udhaar)            ₹40
```

Outstanding Udhaar = **₹0**. The forgiven ₹3 never enters the customer's receivable balance.

If total fee is ₹48, ₹40 is paid and ₹3 is forgiven, only ₹5 remains in Udhaar.

## Grinding rates and Jalan

`RateCard` stores:

- grain type
- output/service
- Jalan / non-Jalan mode
- system rate per kg
- whether an override is allowed
- minimum permitted override
- maximum permitted override
- effective date

Each `GrindingOrderLine` snapshots both the **system rate** and the **applied rate**.

Example seed configuration:

| Service | Jalan | System rate | Minimum |
|---|---:|---:|---:|
| Wheat → Atta | No | ₹2.40/kg | ₹2.00/kg |
| Wheat → Atta | Yes | ₹3.00/kg | ₹2.50/kg |
| Chana → Besan | No | ₹3.00/kg | ₹2.50/kg |
| Multigrain | No | ₹3.50/kg | ₹3.00/kg |
| Mustard oil extraction | No | ₹5.00/kg | ₹4.00/kg |

Changing ₹2.40 to ₹2.00 requires a reason and must stay inside the configured minimum/maximum range.

## Buyback calculation

Example:

- Mustard processed: **15 kg**
- Processing/extraction rate: **₹5/kg**
- Processing fee: **₹75**
- Customer sells Khal to Chakki: **10 kg**
- Buyback rate: **₹20/kg**
- Buyback value: **₹200**
- Net amount returned to customer: **₹200 − ₹75 = ₹125**

The buyback posting also increases the selected inventory item by the bought-back quantity. System rate and applied rate are stored separately, and a reason is mandatory when the applied rate is changed.

# UPI / Dynamic QR configuration — Django Admin only

No UPI VPA, merchant credential or webhook signing secret is configured through the normal ERP screens or `.env` file.

After creating a superuser:

1. Open `/admin/`.
2. Open **Configuration → Payment / UPI gateways**.
3. Edit the seeded disabled `UPI / Bank QR` record or create a new record.
4. Select the provider: UPI/Bank QR, Razorpay, BharatPe or Custom Bank/UPI Provider.
5. Enter the **UPI VPA**.
6. Enter merchant name / merchant ID / API key ID as applicable.
7. Enter the API secret if your provider requires it.
8. Enter a long random **Webhook signing secret**.
9. Set the provider's webhook signature header, e.g. `X-Chakki-Signature` or `X-Razorpay-Signature`.
10. Enable **Active**.
11. Enable **Default gateway** for the preferred provider.
12. Save.

API and webhook secrets are encrypted before storage using an application encryption key derived from `DJANGO_SECRET_KEY`. If `DJANGO_SECRET_KEY` is intentionally changed, re-enter gateway secrets in Admin after the rotation.

The user-facing Settings page only displays configuration state; staff users get direct links to the relevant Django Admin screens.

## QR payment flow

When an operator creates a QR payment:

1. The amount cannot exceed invoice outstanding.
2. Operator selects an active Admin-configured gateway.
3. `OrderPayment` stores the gateway relationship and provider snapshot.
4. A unique `payment_reference` is created.
5. The UPI URI contains the configured VPA, merchant name, amount and unique reference.
6. QR is rendered for the customer.
7. The payment screen HTMX-polls the payment status every three seconds.
8. The bank/provider calls the webhook.
9. The webhook resolves the gateway **from the payment record** and verifies that gateway's signing secret/header.
10. Settlement is executed atomically and idempotently.

### Webhook endpoint

```text
POST /api/v1/payments/qr-webhook/
```

Example payload:

```json
{
  "payment_reference": "QR-ABC123...",
  "status": "SUCCESS",
  "amount": "40.00",
  "provider_payment_id": "provider-transaction-id"
}
```

Default signing method is HMAC-SHA256 over the **exact raw HTTP request body**. The signature header is configured independently for each gateway in Django Admin.

Example Python signature generation:

```python
import hashlib
import hmac
import json

body = json.dumps(
    {
        "payment_reference": "QR-ABC123",
        "status": "SUCCESS",
        "amount": "40.00",
    },
    separators=(",", ":"),
).encode()

signature = hmac.new(
    b"the-webhook-secret-entered-in-django-admin",
    body,
    hashlib.sha256,
).hexdigest()
```

The settlement transaction:

```text
Dr Cash
    Cr Accounts Receivable (Udhaar)
```

It then:

- marks `OrderPayment.settlement_status = SETTLED`
- automatically stamps `settled_at`
- updates invoice paid/outstanding values
- marks the order payment status paid/partial
- closes a fully paid order as Delivered
- returns an `HX-Trigger` event for `paymentSettled`

The provider's HTTP webhook response cannot directly mutate a customer's already-open browser page. Therefore the QR page combines the webhook with HTMX polling; once the database transaction settles, the open screen switches to **Paid & Cleared** automatically.

## RBAC

Application groups:

- **Owner** — full application configuration and financial access.
- **Manager** — operational management and selected accounting.
- **Operator** — grinding, attendance, production and day-to-day floor workflows.
- **Accountant** — receivables, payables, sales/purchases, payroll and reporting.

Django superusers bypass module restrictions. System configuration and payment credentials require Django Admin access (`is_staff`).

## English / Hindi

Django `LocaleMiddleware` is enabled.

- English: `en`
- Hindi: `hi`
- Header switch: **EN / हिं**
- Source translations: `locale/hi/LC_MESSAGES/django.po`
- Compiled translation: `locale/hi/LC_MESSAGES/django.mo`

## Quick start — Windows

```powershell
git clone https://github.com/nasirsaikh/ChakkiApp.git
cd ChakkiApp

py -3.13 -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
npm install
npm run build:css

copy .env.example .env
python manage.py migrate
python manage.py seed_chakki
python manage.py createsuperuser
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/admin/
```

After first login, configure **Payment / UPI gateways** in Django Admin before attempting QR payments.

## Quick start — Linux / macOS

```bash
git clone https://github.com/nasirsaikh/ChakkiApp.git
cd ChakkiApp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm install
npm run build:css
cp .env.example .env
python manage.py migrate
python manage.py seed_chakki
python manage.py createsuperuser
python manage.py runserver
```

## Environment variables

Payment-provider configuration is deliberately **not** present here.

```text
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<long-random-secret>
DJANGO_ALLOWED_HOSTS=chakki.example.com
CSRF_TRUSTED_ORIGINS=https://chakki.example.com
DATABASE_URL=postgresql://user:password@host:5432/chakki
DB_SSLMODE=require
SECURE_SSL_REDIRECT=1
```

`DJANGO_SECRET_KEY` must remain stable because it also protects encrypted payment credentials stored in the database.

## Production deployment

```bash
python manage.py migrate
python manage.py seed_chakki
python manage.py collectstatic --noinput
python manage.py check --deploy
gunicorn chakki_erp.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60
```

Use PostgreSQL for multi-user production. Terminate TLS at Nginx, Caddy, your cloud load balancer or platform ingress. Maintain automatic database backups and periodically test restores.

## Docker

```bash
docker compose up --build
```

Then initialize:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_chakki
docker compose exec web python manage.py createsuperuser
```

UPI/provider configuration is still performed in Django Admin after startup.

## Tests and checks

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
npm run build:css
```

Tests cover:

- balanced double-entry journals
- forgiveness exclusion from Udhaar
- payment webhook signature verification using Admin-configured gateway secrets
- payment amount mismatch rejection
- atomic QR settlement
- invoice/order/payment status updates
- `HX-Trigger` settlement response

GitHub Actions runs the application checks on supported Python versions and builds Tailwind assets.

## Initial migrations

The source tree contains migration packages. A bootstrap GitHub Actions workflow generates and commits initial numbered migrations on `main` if no numbered migration exists yet. Once those files exist, standard migration discipline applies.

For normal feature development:

```bash
python manage.py makemigrations
python manage.py migrate
```

Commit migration files together with the model change that produced them.

## Project structure

```text
chakki_erp/
  settings.py
  urls.py
  asgi.py
  wsgi.py

apps/
  core/             Dashboard, navigation, RBAC, audit model, seed command
  customers/        Customer master/search/history
  accounting/       Accounts, journals, ledger, Udhaar, reports
  operations/       Grinding, rates, invoices, payments, buyback, production, wastage, utilities
  inventory/        Stock, movements, suppliers, purchases, sales
  workforce/        Employees, attendance, payroll, maintenance
  configuration/    Chakki settings + encrypted Admin-only payment gateway configuration

templates/           Django + HTMX + Alpine templates
static_src/          Tailwind/shadcn semantic token source
static/              Built static assets
locale/              English/Hindi localization resources
.github/workflows/   CI and initial migration bootstrap
```

## Security / operational controls

- Never manually edit posted ledger rows. Use compensating/reversal entries for corrections.
- `JournalEntry` and `LedgerEntry` are read-only in Admin.
- Payment webhook secret is provider-specific, encrypted at rest and never displayed back in Admin.
- A webhook is rejected if its payment reference is unknown, gateway is disabled, signature is invalid, status is not settled/success/paid, or amount does not exactly match the pending payment.
- Webhook settlement uses database row locks and is idempotent.
- Do not give ordinary Operators Django Admin access.
- Rate overrides are bounded and require a reason.
- Buyback rate overrides require a reason.
- Opening balances are accounting events and should be loaded only once at go-live.
- PostgreSQL is recommended for production concurrency.
- Use HTTPS in production and run `python manage.py check --deploy` before go-live.

## Repository

`https://github.com/nasirsaikh/ChakkiApp`

## CSS / Tailwind troubleshooting

The repository ships with a development-safe `static/css/app.css`, so Django pages are no longer completely unstyled before the frontend build runs.

For local development:

```bash
python manage.py runserver
```

When `DJANGO_DEBUG=1`, the base template also enables Tailwind CSS v4's browser compiler as a development fallback. This makes all utility classes available immediately while editing templates.

For the production stylesheet, always build the static CSS once after cloning or after changing Tailwind classes:

```bash
npm install
npm run build:css
python manage.py collectstatic --noinput
```

The compiled file must exist at:

```text
static/css/app.css
```

Static URLs are absolute (`/static/`), so the stylesheet resolves correctly from nested routes such as `/customers/`, `/grinding/`, and `/accounts/`.
