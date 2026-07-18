# Ustudy ERP — Education Center Management

Custom Odoo 19 add-ons powering **Ustudy** (erpustudy.uz): an education-center
ERP covering students, courses, groups, scheduling, attendance, homework &
grading, finance, dashboards, and external integrations (CRM/Facebook,
telephony, biometric attendance).

## Environment

| | |
|---|---|
| Odoo version | 19 (`/opt/education/odoo19`) |
| Database | `education` |
| Service | `odoo.service` — `systemctl restart odoo` |
| Config | `/opt/server/conf/odoo.conf` (`workers = 0`, threaded) |
| Log | `/opt/server/log/odoo.log` |
| Addons path | `/opt/education/custom-addons` |
| Python venv | `/opt/education/venv` |

Deploy a change: `-u <module>` on the module whose version was bumped, then
restart the service.

## Module map

Modules are grouped by domain. **Bold** = project-specific; the rest are
third-party / OCA / theme add-ons vendored into the repo.

### Core education domain

| Module | Ver | Purpose |
|---|---|---|
| **ustudy_student** | 1.0 | Base of the domain. Students on `res.partner`, `edu.course`, `edu.enrollment`, `cc.region` (viloyat/tuman geography). |
| **ustudy_course** | 19.0.1.0.0 | Course structure on top of website_slides: `ustudy.course.module` → `ustudy.course.lesson` → {video, files, homework}. |
| **ustudy_group** | 1.11.0 | Central module. Groups & rosters (`edu.group`, `edu.group.student`), scheduling (`edu.timetable`, `edu.room`, `edu.weekday`), attendance (`edu.attendance`, `edu.attendance.line`, `edu.davomat.matrix` OWL grid), modules/lessons, camera & add-student wizards, per-student lesson report. Talabalar roster list lives here. |
| **ustudy_homework** | 1.7.4 | Homework & grading: `edu.homework`, `edu.homework.submission`, `edu.homework.mark`, lesson-complete wizard, and the `edu.student.lesson.report` SQL view driving the Vazifalar roster + grading. |

### Finance

| Module | Ver | Purpose |
|---|---|---|
| **edu_finance** | 19.0.1.1.0 | Income/expense for the center: `cc.finance`, `cc.payment.method`, `cc.payment.type`. |
| **ustudy_group_finance** | 19.0.1.0.0 | Connects groups ↔ finance: student payments, module-payment wizard, per-student lesson payment report, smart buttons. |

### Dashboards & scheduling boards

| Module | Ver | Purpose |
|---|---|---|
| **ustudy_dars_jadvali** | 1.1.1 | Excel-style room×time schedule board (`dars.jadvali.board`) with Reja/Fakt totals and card→wizard editing. |
| **ustudy_dashboard** | 1.0 | Interactive admin eLearning dashboard (`elearning.dashboard`). |

### eLearning / media

| Module | Ver | Purpose |
|---|---|---|
| **elearning_core** | 19.0.1.0.0 | website_slides tweaks: hide extra sections, publish all lessons. |
| **ustudy_video_upload** | 1.0.0 | Upload video files directly onto eLearning slides. |

### Integrations

| Module | Ver | Purpose |
|---|---|---|
| **crm_fb_webhook** | 19.0.1.0.0 | Facebook Lead Ads → CRM via OAuth2 + webhook (`fb.page`, `fb.lead.form`, `fb.field.mapping`). |
| **onlinepbx_calls** | 19.0.1.0.0 | OnlinePBX call history via webhook, call rating/scoring (`onlinepbx.call`, `onlinepbx.call.rating`, `onlinepbx.score.category`, `onlinepbx.objection`, `onlinepbx.settings`). |
| **hikvision_attendance** | 19.0.1.0.0 | Hikvision DS-K1T320 biometric attendance webhook → `hr_attendance` (controllers only, no models). |
| **ustudy_notebook_mgmt** | 1.0 | Notebook/asset lending: `edu.notebook`, `edu.notebook.borrow`. |

### UI / UX add-ons

| Module | Purpose |
|---|---|
| **web_save_button** | Makes the form Save button more prominent. |
| **web_chatter_default_closed** | Collapses the chatter by default. |
| dark_backend_theme, muk_web_theme*, oca_web, server-backend, web, web_timeline | Vendored theme / OCA backend libraries. (*muk_web_theme lives at `/opt/education/muk_web_theme-19.0.1.4.0`.) |

## Dependency graph (project modules)

```
website_slides ─┬─ ustudy_course ──┐
                ├─ elearning_core  │
                └─ ustudy_video_upload
contacts ──────── ustudy_student ──┴─ ustudy_group ──┬─ ustudy_homework
hr, project,                                         ├─ ustudy_dars_jadvali
crm, event, mail ────────────────────────────────────┤
                                     edu_finance ─────┴─ ustudy_group_finance
crm ───────────── crm_fb_webhook
contacts, hr ──── onlinepbx_calls
hr_attendance ─── hikvision_attendance
```

`ustudy_group` is the hub: install/upgrade order is
`ustudy_student → ustudy_course → ustudy_group → ustudy_homework`, then finance
(`edu_finance → ustudy_group_finance`) and the dashboards/boards.

## Repository layout

```
/opt/education/
├── odoo19/                 # Odoo 19 core (upstream)
├── venv/                   # Python virtualenv
├── custom-addons/          # ← this repo (add-ons above)
├── muk_web_theme-19.0.1.4.0/
├── backup/
└── *.py                    # one-off maintenance / data-repair scripts
```

A typical add-on follows Odoo conventions: `models/`, `views/`, `security/`,
`data/`, `wizard/`, `controllers/`, `static/src/` (OWL/JS), `migrations/`.

## Maintenance scripts

One-off `odoo-bin shell` scripts at the repo root, for data repairs (see git
history / module notes for context before re-running):

- `fix_timetable_names.py` — normalize timetable names.
- `fix_timetable_slide_drift.py` — repair No.↔slide.lesson_no drift.
- `fix_u18_students.py` — dedupe/repair U18 student attendance lines.
- `realign_group_lessons.py` — re-align group lesson numbering.

## Conventions

- **Bump the module `version`** in `__manifest__.py` for every change so the
  upgrade is picked up; deploy with `-u <module>`.
- The heavy `edu.student.lesson.report` SQL view (~22k rows) is expensive to
  materialize — **batch computes** that read it with a single `_read_group`,
  never one `search_count` per record (see `ustudy_homework/models/res_partner.py`).
- UI language is Uzbek (Latin) with some Cyrillic; keep field/label strings
  consistent with the existing views.
