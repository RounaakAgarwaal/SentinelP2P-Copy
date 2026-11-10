# Setup and local operation

SentinelP2P's normal local runtime is one FastAPI process serving both its API
and the built React application. The scripts do not start Vite's development
server, run generators or training, install Ollama, download a model, or
rewrite project data.

## Prerequisites

Install these tools yourself before setup:

- Python 3.10+.
- `uv` available on `PATH`.
- Node.js 20.19+ or 22.12+ and npm.
- Bash on Linux; PowerShell 5.1+ on Windows 10/11.

The setup scripts report detected versions and do not silently upgrade Python,
Node.js, npm, or `uv`, and do not invoke `sudo` or require administrator
privileges. For Python dependencies, they use an already active
`VIRTUAL_ENV`/`CONDA_PREFIX`, otherwise an existing usable project `.venv`,
otherwise create `.venv` with `uv`. They never delete or replace an environment.
If an active environment is selected, it is the user's responsibility to
activate the intended environment first.

## Linux

From the repository root:

```bash
./setup.sh
./start.sh
```

Open <http://127.0.0.1:8000>. Stop only processes launched by these scripts:

```bash
./stop.sh
```

Check prerequisites without installing packages or creating local state:

```bash
./setup.sh --check-only
```

## Windows 10/11

From Command Prompt or PowerShell, in the repository root:

```bat
setup.bat
start.bat
```

Open <http://127.0.0.1:8000>, then stop script-owned processes with:

```bat
stop.bat
```

The `.bat` files invoke the PowerShell helpers in `scripts/`. Prerequisite-only
check:

```bat
setup.bat -CheckOnly
```

Paths are resolved from the script location, so the repository may be cloned
to a path containing spaces. If PowerShell execution is restricted by local
policy, the launcher uses a process-scoped `-ExecutionPolicy Bypass`; it does
not change the machine or user policy.

## Dependency groups and test commands

Normal setup installs only `backend/requirements.txt` and runs `npm ci` plus a
production frontend build. It does not install Streamlit or the ML/training
stack.

| File | Purpose |
| --- | --- |
| `backend/requirements.txt` | FastAPI application runtime, Uvicorn, LangGraph investigation integration, requests, dotenv |
| `requirements-dev.txt` | Backend runtime plus `httpx` for API tests |
| `requirements-streamlit.txt` | Optional internal Streamlit dashboard |
| `requirements-ml.txt` | Optional dataset generation, model training, and extended RAG/graph packages |
| `requirements-phase3.txt` | Legacy Phase 3 list; retained for compatibility, not the standard install target |

Install development test dependencies into the project environment and run
the suite:

Linux:

```bash
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

Windows:

```bat
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Replace the interpreter path with the active environment's Python when setup
used an already active environment. The React production build is performed
by setup; to build manually use `npm ci` and `npm run build` in `frontend/`.

## Configuration

Setup creates root `.env` from `.env.example` only if `.env` does not exist. It
does not overwrite a user's existing configuration or secrets. Configuration
is loaded from the repository root by the backend. Relative data paths are
resolved from the repository root; run application commands with the
repository as the working directory.

Common settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SENTINEL_DATA_DIR` | `./data` | Existing project data directory |
| `SENTINEL_INVESTIGATION_DB` | `./data/investigations.sqlite3` | SQLite investigation store |
| `SENTINEL_API_HOST` | `127.0.0.1` | Local API bind address |
| `SENTINEL_API_PORT` | `8000` | API and React application port |
| `SENTINEL_STREAMLIT_PORT` | `8501` | Optional Streamlit port |
| `CORS_ORIGINS` | Local Vite origins | Development CORS allowlist |
| `VITE_API_BASE_URL` | `/api` | Frontend API prefix, supplied during production build |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama HTTP endpoint |
| `OLLAMA_MODEL` | empty | Installed Ollama model name; blank disables local answer generation |
| `OLLAMA_TIMEOUT` | `120` | Local generation request timeout in seconds |
| `TAVILY_API_KEY` | empty | Optional external business research for investigations only |

Keep secrets only in root `.env` or an appropriate backend environment. Never
put credentials in `frontend/.env*`: Vite embeds frontend variables in browser
files. Ollama is local answer generation; Tavily is a separate, optional
external business-search integration in the investigation workflow.

## Optional Streamlit dashboard

Install its packages separately, then start it alongside FastAPI:

Linux:

```bash
./setup.sh --with-streamlit
./start.sh --streamlit
```

Windows:

```bat
setup.bat -WithStreamlit
start.bat -Streamlit
```

The Streamlit dashboard is available at <http://127.0.0.1:8501>. `stop` stops
both services started by the scripts. It uses the existing repository data;
the scripts do not generate or replace dashboard inputs.

## Optional Ollama

Ollama and model download are user-managed and are not prerequisites for the
application. Install Ollama from its official distribution for your OS, start
its local service, then download a model suited to the machine's RAM and
hardware. For example, after installing Ollama, use its CLI to pull the model
you selected and set `OLLAMA_MODEL` in root `.env` to that exact installed
model name. No model is selected automatically because hardware differs.

On Linux, follow the official Ollama Linux installation instructions and run
the local Ollama service under the user's account. Do not expose the service to
the network: Sentinel AI is designed to use the local endpoint only. On
Windows/macOS, use the official Ollama installer/application. Start SentinelP2P
after Ollama is available; if Ollama is absent, Sentinel AI reports the local
provider as unavailable rather than falling back to a cloud provider.

## Ports, logs, and state

The default API host/port are `127.0.0.1:8000`; optional Streamlit uses
`127.0.0.1:8501`. Set `SENTINEL_API_HOST`, `SENTINEL_API_PORT`, or
`SENTINEL_STREAMLIT_PORT` in the shell before starting to override these.
Setup and startup detect occupied ports and report a recovery action; they do
not terminate an unrelated process.

Process records and logs are stored under `.sentinelp2p/` (ignored by Git).
Linux logs append to `.sentinelp2p/logs/`. Windows logs are stored separately
for standard output and errors. The stop scripts validate recorded process
identity before signaling it; they do not stop unrelated applications.

## Data preservation and backup

Setup reads existing datasets and artifacts but does not regenerate CSVs,
train or overwrite models, initialize/replace SQLite databases, or alter
vector data. Keep independent backups of local business records,
`data/investigations.sqlite3`, vector stores, and generated artifacts. SQLite
WAL/SHM files are runtime state and should be backed up using a consistent
SQLite backup method rather than copied while writes are active.

The root `.gitignore` excludes local environments, secrets, runtime state,
databases, caches, and generated model outputs. It deliberately does not
exclude source/demo datasets or `test_data/` fixtures. Review `git status` and
the staged file list before publishing a public repository.

## Troubleshooting

- **Missing `uv`, Python, Node, or npm:** install the prerequisite manually and
  rerun the setup command. Setup never upgrades system tools.
- **Unsupported Python/Node version:** install a supported version side by
  side and select it in `PATH`; no existing installation is changed.
- **Port is busy:** stop the service that owns it, or select a free port using
  the corresponding environment variable before startup.
- **Frontend files are missing:** run setup again to install frontend packages
  and rebuild `frontend/dist`.
- **API fails to start:** inspect `.sentinelp2p/logs/` and verify core backend
  dependencies are installed into the Python environment recorded by setup.
- **Ollama is unavailable or model missing:** start Ollama and install a model
  yourself, then check `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in `.env`.
- **Windows PowerShell unavailable:** install/enable Windows PowerShell 5.1 or
  newer; the `.bat` scripts depend on it.
