# School ERP — ready-to-run Django project

This project starts with four apps:

| App | Responsibility |
| --- | --- |
| `core` | Reusable permission and branch-scoping helpers |
| `accounts` | Custom email login and roles |
| `branches` | Campus / branch records |
| `staff` | Employee profiles |

## Run it

Use Python 3.10 or newer, then run these commands from this folder.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py manage.py migrate
py manage.py createsuperuser
py manage.py runserver
```

Open `http://127.0.0.1:8000/`. Sign in at `http://127.0.0.1:8000/accounts/login/` or use `http://127.0.0.1:8000/admin/` to create the first branch and users.

## Access model

- **Django superuser**: full access including Django admin.
- **System admin** (`SYSTEM_ADMIN`): manages every branch and all staff from the ERP screens.
- **Finance admin** (`FINANCE_ADMIN`): assign one or more branches in **Accessible branches**; use this role for the future finance module.
- **Branch admin** (`BRANCH_ADMIN`): sees and manages staff belonging to their assigned branch(es) only.
- **Staff** (`STAFF`): can view only their assigned branch(es) and its staff directory.

## Creating staff users

Use **Staff → Add staff** in the ERP. One form creates both the login account and the employment profile:

- Enter email and password for the staff member.
- Choose **System admin** for access to every branch. Select a primary/home branch so the staff record is correctly listed and reported.
- Choose **Finance admin** and select every branch the finance team should access.
- Choose **Branch admin** or **Staff** and select one primary branch. That branch is automatically their only accessible branch.

A real Django **superuser** is deliberately created only with `py manage.py createsuperuser`; it grants access to Django's technical `/admin/` site. For a staff member who should manage all ERP branches, use **System admin** instead.

## Password reset through SMTP

Copy `.env.example` to `.env`, then provide your mail provider's SMTP host, port, username, and an **app password** (not your normal mailbox password). The login page then shows **Forgot password?**. Reset links are sent only to active staff accounts.

Configuration is split into `config/settings_base.py`, `config/settings_development.py`, and `config/settings_production.py`. Locally it uses SQLite and development settings. Production requires PostgreSQL: set `DJANGO_ENV=production`, database credentials, a unique `SECRET_KEY`, and your HTTPS domain in `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, then run:

```bash
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 0.0.0.0:8000
```

Place the app behind an HTTPS reverse proxy such as Nginx or a cloud load balancer.

## Staff leaving the school

Use **Staff → Mark left**, enter their leaving date and reason, and submit. This disables the login immediately and preserves the staff record, including its exit information, for reporting.

## Staff documents

Staff profiles include address and address proof. System admins and Django superusers can open **Documents** beside a staff member, record education, upload supporting files, and download them through a permission-checked route. Uploaded files are held in `private_media` and are not linked as public media URLs.

## Important implementation rule

The custom user model is already configured with `AUTH_USER_MODEL = "accounts.User"`. Do not replace it after applying migrations; it should remain the project user model permanently.

## Next modules

Follow the same model ownership rule for students, attendance, fees, and exams: give each record a `branch` field and call `branch_scope(request.user, queryset)` in its list and detail views.
