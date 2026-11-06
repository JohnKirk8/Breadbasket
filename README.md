# BreadBasket (BB App) — Django starter

This is a working Django conversion of your HTML/CSS/JS prototype: real
authentication (Django's built-in auth + Groups for Admin / Baker /
Inventory Staff roles), a real MySQL/SQLite-backed database instead of
in-memory JS arrays, and a Gemini API integration for the AI production
forecast, with a safe fallback if the API isn't reachable.

## 1. Set up your environment

Requires **Python 3.10+** (the code uses `str.removeprefix`, added in 3.9,
and Django 4.2 needs 3.10+).

```bash
cd breadbasket_django
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and, at minimum, leave `DB_ENGINE=sqlite` for now (fastest way
to get running). You can switch to MySQL later — see step 5.

## 2. Create the database tables

```bash
python manage.py makemigrations inventory
python manage.py migrate
```

## 3. Create roles, demo users, and sample data

```bash
python manage.py seed_data
```

This creates the three Groups, sample bakery data, and these ready-to-use
accounts (password for all is `breadbasket123`):

| Username | Role | What they can do |
|----------|------|------------------|
| `admin`  | Administrator / Owner | Everything (also works in `/admin/`) |
| `baker`  | Baker | AI planner, catalog (read), ingredients (read), log batches, reports |
| `staff`  | Inventory Staff | AI planner (read), catalog (read), restock ingredients, sales, reports |

```bash
python manage.py runserver
```

## 4. Try it out

Go to `http://127.0.0.1:8000/login/` and sign in with any demo account above. You should see:

- **AI Production Planner** — shows "Not yet forecasted" until an Admin
  clicks "Refresh AI Forecast" (this is the button that calls Gemini).
- **Bread Catalog & Recipes**, **Raw Ingredients**, **Sales Transactions**,
  **System Reports** — same tabs as your prototype, now backed by the
  database and restricted by role, same as your data-roles attributes did.

## 5. Turn on the AI forecast (Gemini API)

1. Get a free key at https://aistudio.google.com/app/apikey
2. Put it in `.env` as `GEMINI_API_KEY=...`
3. Restart the server, log in as an Admin/superuser, and click
   **"Refresh AI Forecast"** on the AI Production Planner tab.
4. If the key is missing or the request fails for any reason, the app
   automatically falls back to a 110%-of-recent-average calculation
   instead of crashing — check the "Source" column to see which one was
   used (`gemini` vs `fallback`).

**Test the API by itself first.** Before trusting it from Django, send a
POST request in Postman to:

```
https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent
Header: x-goog-api-key: YOUR_KEY
Body:
{
  "contents": [{"parts": [{"text": "Explain how AI works in a few words"}]}]
}
```

If that works in Postman, it'll work from `inventory/ai_forecast.py`.

## 6. Switching to MySQL (your XAMPP setup)

1. Start MySQL from XAMPP and create a database (e.g. via phpMyAdmin):
   `CREATE DATABASE breadbasket_db;`
2. In `.env`, set `DB_ENGINE=mysql` and fill in `DB_NAME`, `DB_USER`,
   `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (defaults match XAMPP's usual
   `root` user with no password on `127.0.0.1:3306`).
3. Re-run `python manage.py migrate` (and `seed_data` again if this is a
   fresh database).

## Project structure

```
breadbasket_django/
  manage.py
  requirements.txt
  .env.example
  breadbasket_project/     <- Django project settings/urls
  inventory/                <- the actual app (this is where you'll work)
    models.py                Ingredient, Product, RecipeItem, ProductionBatch,
                              SalesRecord, AIRecommendation
    views.py                 one view per tab/action from your prototype
    forms.py                 restock / log batch / record sale / add product forms
    ai_forecast.py            <-- the Gemini integration lives here
    decorators.py             @role_required(...) — role-based access control
    context_processors.py     makes is_admin/is_baker/is_inventory available
                               in every template automatically
    templates/inventory/      one HTML file per tab, extending base.html
    static/inventory/css/     your original stylesheet, unchanged
    management/commands/
      seed_data.py            creates the 3 groups + 3 demo users + sample data
```

## Demo logins (after `seed_data`)

| Username | Password | Role |
|----------|----------|------|
| `admin` | `breadbasket123` | Administrator (full access + Django admin) |
| `baker` | `breadbasket123` | Baker |
| `staff` | `breadbasket123` | Inventory Staff |

## What to build next

- Wire up a real "Users" self-registration flow if your project needs it
  (demo accounts are already seeded; extra accounts can still be created
  through `/admin/` by logging in as `admin`).
- Expand `ai_forecast.py`'s prompt if you want the AI to factor in
  day-of-week patterns, upcoming holidays, etc.
- Add unit tests for the ingredient-deduction logic in `views.log_batch` —
  that's the part most worth double-checking before your defense.
