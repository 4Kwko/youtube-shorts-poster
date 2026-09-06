# Repository Guidelines

## Project Structure & Module Organization

`backend/app/` contains the FastAPI application: routes are in `api/routes/`, durable data types in `models/` and `schemas/`, and domain work in `services/`. Database migrations live in `backend/alembic/versions/`. The desktop client is in `frontend/`: React code is under `src/`, Tauri/Rust integration under `src-tauri/`, and styles under `src/styles/`. Python tests are in `tests/`; frontend unit tests sit beside their `src/lib/` modules. Utility and smoke-test scripts belong in `scripts/`.

Keep generated files, downloaded media, and local databases in `storage/`; they are intentionally ignored. Never commit `.env` files—start from `.env.example` instead.

## Build, Test, and Development Commands

- `python -m pytest` — run the backend test suite from the repository root.
- `ruff check backend tests` — lint Python code; `mypy backend` — run strict type checks.
- `cd frontend; npm run dev` — start the web client.
- `cd frontend; npm run build` — type-check and build the frontend.
- `cd frontend; npm run lint` and `npm test` — lint and run Vitest tests.
- `powershell -ExecutionPolicy Bypass -File scripts/dev-desktop.ps1` — run the local desktop workflow.

Use Python 3.12+ and the checked-in `frontend/package-lock.json` with `npm ci` for repeatable client installs.

## Coding Style & Naming Conventions

Python uses four spaces, type annotations, and Ruff’s 100-character line limit. Keep service modules focused; use `snake_case` for functions/files and `PascalCase` for classes. TypeScript and React use two spaces, `camelCase` functions, `PascalCase` components, and component file names such as `ProjectCard.tsx`. Run the configured linters instead of manually reformatting generated migrations or schemas.

## Testing Guidelines

Name Python tests `test_<behavior>.py` and frontend tests `<module>.test.ts`. Add coverage for successful flows, validation failures, and media-processing edge cases. Run the targeted tests while developing and both test suites before submitting a pull request.

## Commit & Pull Request Guidelines

Use imperative Conventional Commit subjects: `feat: add export preset`, `fix: handle missing audio`, or `docs: update setup`. Pull requests need a concise summary, testing notes, linked issue when applicable, and screenshots or a short recording for visual client changes. Do not include generated media, build products, local databases, or credentials.
