# SentinelP2P frontend and API

## Production build and startup

From the repository root, build the React application:

```bash
npm ci --prefix frontend
npm run build --prefix frontend
```

Start FastAPI from the repository root. It serves the built React files and API
from one local origin (`http://127.0.0.1:8000`):

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The frontend uses `/api` for API calls. If the
build output or `frontend/dist/index.html` is missing, the backend returns an
HTTP 503 response with the build command to run.

## Development with Vite

Run the API from the repository root:

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

In another terminal, run Vite:

```bash
npm run dev --prefix frontend
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` requests to the local FastAPI
server, so the browser uses the same `/api` URL in development and production.
