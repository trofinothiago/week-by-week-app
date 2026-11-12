# Week by Week (our own app)

Thiago and Rory's household money system, as an app of our own. Not for sale.

- `src/week-by-week.html` is the page as it is inside Claude, plus what only the app has (Rory's answers from his own
  account, step 2a; notifications, step 2b). Every change is tested with the app's kit before it's published.
- `python3 tools/build.py` makes `index.html` (the page + its data connection) and `import.html` (the account page).
- `app/bridge.js` gives the page what it asks for (`window.claude.use('db' | 'user' | 'downloads' | 'notify')`) from Supabase:
  sign-in, the `docs` table, live updates, and notifications on this phone. `sw.js` only shows pushed notifications and
  opens the app on a tap (it caches nothing). The sender is the Edge Function in `supabase/functions/push`. `app/config.js` holds the project URL and the publishable key (public by design).
- `supabase/001_base.sql`: the tables and the locks (Row Level Security). Thiago (editor) writes; Rory (viewer) reads;
  nobody else sees anything. `002_rory_answers.sql`: Rory's own answers. `003_notifications.sql` and `004_push_sender.sql`:
  who is told what, each person's choices and quiet hours, the queue, and the sender's wake-up (pg_cron, Vault).
- Tests: `test/smoke.py` (sign-in, roles, invite link, import, phone fit, with a fake Supabase);
  `test/make_kit.py` turns the WBW System Kit into the app's kit (the page played through the app's own connection);
  the SQL is tested on a local Postgres with `test/rls_test.mjs`, `test/answers_test.mjs` and `test/push_test.mjs` (PGlite);
  the sender's Web Push code with `test/webpush_test.mjs`, the service worker with `test/sw_test.mjs`;
  `test/backup_to_data.py` turns a backup into the kit's data folder (never commit a backup: this repository is public).
