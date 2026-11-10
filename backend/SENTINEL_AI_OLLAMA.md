# Sentinel AI with local Ollama

Sentinel AI sends answer-generation requests only to an HTTP loopback Ollama endpoint. The backend rejects non-loopback addresses, disables proxy use and redirects, and rejects Ollama cloud model tags. It does not use Tavily or another provider for chat answers. Retrieval remains read-only and supplies the records and source IDs used to ground the response.

## Install Ollama on Linux

Install Ollama using the [official Linux download instructions](https://ollama.com/download/linux):

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

The command above installs Ollama; it does not choose a model. Model resource needs vary by model and machine. Check the selected model's requirements against the computer's available memory and hardware before downloading it.

## Select and start a local model

Choose a model that is appropriate for the machine and is available for local use in the [Ollama model library](https://ollama.com/library). Then pull and run that exact local model tag:

```bash
ollama pull <local-model-tag>
ollama list
ollama serve
```

If Ollama is already running as a system service, `ollama serve` may report that its port is already in use; leave the existing local service running. Do not select a model tag marked `:cloud` or `-cloud`. This integration rejects those tags because they may route inference outside the machine.

Ollama's local API listens on `127.0.0.1:11434` by default. Sentinel AI calls the local `/api/chat` endpoint with streaming disabled and a JSON response format.

## Configure SentinelP2P

The repository-root `.env.example` contains non-secret defaults. Backend settings load the repository-root `.env` consistently on Linux and Windows; process environment values take precedence. If `.env` does not already exist, copy the example without overwriting an existing one:

```bash
if [ ! -e .env ]; then cp .env.example .env; fi
```

Set `OLLAMA_MODEL` to the exact model tag shown by `ollama list`. For example, set it to `<local-model-tag>` after pulling that model. Configure these values in the process environment or repository-root `.env`:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=<local-model-tag>
OLLAMA_TIMEOUT=120
```

Start FastAPI from the repository root so relative data paths resolve consistently:

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

When `OLLAMA_MODEL` is empty, the endpoint returns `provider_not_configured` and does not make a request. If Ollama is unreachable, the model is missing, the request times out, or the response is malformed, the API returns a provider error without an external fallback. No credentials are required or sent to Ollama.

## Evidence and limitations

Retrieved records and conversation history are marked as untrusted context in the model prompt. History is context only, not evidence. The backend withholds responses with citation IDs that are absent from the current retrieval result, and it withholds outputs that match the prohibited fraud-classification or payment-action checks. These controls reduce risk but do not guarantee every model statement is supported; auditors must review the cited source records. No model, Ollama installation, or model download is included in this project task.
