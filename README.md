# Week by Week (our own app)

Thiago and Rory's household money system, as an app of our own. Not for sale.

- `src/week-by-week.html` is the page exactly as it is inside Claude. It is never edited here: changes are made in the
  Claude project chat, tested with the kit, then copied in.
- `python3 tools/build.py` makes `index.html` (the page + its data connection) and `import.html` (the account page).
- `app/bridge.js` gives the page what it asks for (`window.claude.use('db' | 'user' | 'downloads')`) from Supabase:
  sign-in, the `docs` table, live updates. `app/config.js` holds the project URL and the publishable key (public by design).
- `supabase/001_base.sql`: the tables and the locks (Row Level Security). Thiago (editor) writes; Rory (viewer) reads;
  nobody else sees anything.
- Tests: `test/smoke.py` (sign-in, roles, invite link, import, phone fit, with a fake Supabase);
  `test/make_kit.py` turns the WBW System Kit into the app's kit (the page played through the app's own connection);
  the SQL is tested on a local Postgres with `test/rls_test.mjs` (PGlite).
