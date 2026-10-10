# Static presentation demo

What Vercel serves (see `vercel.json`): the real DropOS UI from `backend/frontend`, with
`demo.js` answering every `/api` call from `fixtures.json`. No server, no database, no login.
Buttons work visually, but nothing is saved.

Rebuild the sample data (needs a throwaway Postgres):

```bash
DATABASE_URL=postgresql://... python demo/tools/seed.py          # sample products + demo/img/*.svg
AUTH_DISABLED=1 DATABASE_URL=postgresql://... uvicorn main:app   # from backend/
python demo/tools/record.py http://localhost:8000                # → demo/fixtures.json
bash demo/build.sh                                               # → dist/ (open dist/index.html via any static server)
```
