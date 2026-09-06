//! Gerência dos processos do motor local (migrations, FastAPI e worker).
//!
//! Escopo de desenvolvimento: usa o Python do `.venv` do próprio repositório.
//! Nada é empacotado ainda — nem Python, nem FFmpeg, nem modelo do Whisper.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

pub const DEFAULT_PORT: u16 = 8000;

/// Espera máxima pelo `/health` depois de subir o FastAPI.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);
const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(400);
const CONNECT_TIMEOUT: Duration = Duration::from_millis(600);
/// Tempo dado ao processo para sair sozinho antes do kill forçado.
const SHUTDOWN_GRACE: Duration = Duration::from_secs(5);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    /// Ainda não começou (janela recém-aberta).
    Idle,
    Migrating,
    Starting,
    Ready,
    Failed,
}

#[derive(Debug, Clone, Serialize)]
pub struct EngineStatus {
    pub phase: Phase,
    pub message: Option<String>,
    pub port: u16,
    /// Verdadeiro quando encontramos um backend já no ar e apenas o reusamos.
    pub reused: bool,
}

/// Caminhos derivados da raiz do repositório. Nada de caminho absoluto fixo.
#[derive(Debug, Clone)]
pub struct ProjectPaths {
    pub root: PathBuf,
    pub backend: PathBuf,
    pub python: PathBuf,
}

impl ProjectPaths {
    pub fn discover() -> Result<Self, String> {
        let root = find_project_root()?;
        let backend = root.join("backend");
        let python = find_python(&root)?;
        Ok(Self {
            root,
            backend,
            python,
        })
    }
}

/// Sobe a partir do diretório atual até achar a raiz do repositório.
///
/// Em `tauri dev` o processo roda em `frontend/src-tauri`; num build, no
/// diretório do binário. Procurar pelos marcadores evita depender de qual dos
/// dois é o caso.
fn find_project_root() -> Result<PathBuf, String> {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
        }
    }

    for candidate in candidates {
        let mut current: Option<&Path> = Some(candidate.as_path());
        while let Some(dir) = current {
            if dir.join("pyproject.toml").is_file() && dir.join("backend").is_dir() {
                return Ok(dir.to_path_buf());
            }
            current = dir.parent();
        }
    }

    Err("Raiz do projeto não encontrada (esperado um diretório com pyproject.toml e backend/).".into())
}

fn find_python(root: &Path) -> Result<PathBuf, String> {
    let candidates = [
        root.join(".venv").join("Scripts").join("python.exe"),
        root.join(".venv").join("bin").join("python"),
    ];

    for candidate in candidates {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }

    Err(format!(
        "Ambiente virtual não encontrado em {}. Crie com: python -m venv .venv && .venv/Scripts/pip install -e \".[dev]\"",
        root.join(".venv").display()
    ))
}

fn base_command(paths: &ProjectPaths) -> Command {
    let mut command = Command::new(&paths.python);
    command
        .current_dir(&paths.root)
        .env("PYTHONPATH", &paths.backend)
        // Sem isto o log do Python fica preso no buffer e só aparece no fim.
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    command
}

/// Repassa stdout/stderr do processo filho para o terminal do Tauri.
fn pipe_output(child: &mut Child, label: &'static str) {
    if let Some(stdout) = child.stdout.take() {
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                println!("[{label}] {line}");
            }
        });
    }
    if let Some(stderr) = child.stderr.take() {
        thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                eprintln!("[{label}] {line}");
            }
        });
    }
}

/// `GET /health` cru sobre TCP. Evita trazer um cliente HTTP só para isto.
fn probe_health(port: u16) -> Option<String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&address, CONNECT_TIMEOUT).ok()?;
    stream.set_read_timeout(Some(CONNECT_TIMEOUT)).ok()?;
    stream.set_write_timeout(Some(CONNECT_TIMEOUT)).ok()?;

    let request = format!(
        "GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    stream.flush().ok()?;

    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    let _ = stream.shutdown(Shutdown::Both);

    if response.is_empty() {
        None
    } else {
        Some(response)
    }
}

/// Só reutilizamos a porta se quem responde for o nosso backend.
fn is_our_backend(response: &str) -> bool {
    response.contains("200 OK") && response.contains("\"status\":\"ok\"") && response.contains("clipper")
}

fn port_is_free(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, CONNECT_TIMEOUT).is_err()
}

fn wait_for_health(port: u16, child: &mut Child) -> Result<(), String> {
    let deadline = Instant::now() + HEALTH_TIMEOUT;

    while Instant::now() < deadline {
        // Se o processo morreu, esperar o health seria esperar para sempre.
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "O backend encerrou antes de responder (código {status}). Veja o log [backend]."
            ));
        }

        if let Some(response) = probe_health(port) {
            if is_our_backend(&response) {
                return Ok(());
            }
        }

        thread::sleep(HEALTH_POLL_INTERVAL);
    }

    Err(format!(
        "O backend não respondeu em /health dentro de {}s.",
        HEALTH_TIMEOUT.as_secs()
    ))
}

fn terminate(child: &mut Child, label: &str) {
    if matches!(child.try_wait(), Ok(Some(_))) {
        return;
    }

    #[cfg(windows)]
    {
        // /T derruba a árvore: o uvicorn pode ter processos filhos.
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    #[cfg(not(windows))]
    {
        let _ = child.kill();
    }

    let deadline = Instant::now() + SHUTDOWN_GRACE;
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => return,
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(_) => break,
        }
    }

    // Último recurso: mata direto e não espera mais.
    let _ = child.kill();
    let _ = child.wait();
    eprintln!("[engine] {label} não encerrou no tempo esperado; kill forçado.");
}

#[derive(Default)]
struct EngineInner {
    phase_message: Option<String>,
    phase: Option<Phase>,
    backend: Option<Child>,
    worker: Option<Child>,
    reused: bool,
    starting: bool,
}

/// Handle compartilhado. Uma instância por processo Tauri.
#[derive(Clone)]
pub struct Engine {
    inner: Arc<Mutex<EngineInner>>,
    port: u16,
}

impl Engine {
    pub fn new(port: u16) -> Self {
        Self {
            inner: Arc::new(Mutex::new(EngineInner::default())),
            port,
        }
    }

    pub fn status(&self) -> EngineStatus {
        let inner = self.inner.lock().expect("estado do motor envenenado");
        EngineStatus {
            phase: inner.phase.unwrap_or(Phase::Idle),
            message: inner.phase_message.clone(),
            port: self.port,
            reused: inner.reused,
        }
    }

    fn set_phase(&self, phase: Phase, message: Option<String>) {
        let mut inner = self.inner.lock().expect("estado do motor envenenado");
        inner.phase = Some(phase);
        inner.phase_message = message;
    }

    /// Impede duas inicializações simultâneas (hot reload, reabertura).
    fn claim_startup(&self) -> bool {
        let mut inner = self.inner.lock().expect("estado do motor envenenado");
        if inner.starting || inner.phase == Some(Phase::Ready) {
            return false;
        }
        inner.starting = true;
        true
    }

    fn release_startup(&self) {
        let mut inner = self.inner.lock().expect("estado do motor envenenado");
        inner.starting = false;
    }

    pub fn start(&self) {
        if !self.claim_startup() {
            return;
        }

        let result = self.start_inner();
        self.release_startup();

        match result {
            Ok(()) => self.set_phase(Phase::Ready, None),
            Err(error) => {
                eprintln!("[engine] falha ao iniciar: {error}");
                self.set_phase(Phase::Failed, Some(error));
            }
        }
    }

    fn start_inner(&self) -> Result<(), String> {
        // Backend já no ar: reaproveita em vez de brigar pela porta.
        if let Some(response) = probe_health(self.port) {
            if is_our_backend(&response) {
                // Backend externo (dev-desktop.ps1, uvicorn manual): quem o
                // subiu também é dono do worker. Iniciar outro aqui só
                // duplicaria processos — o claim atômico evitaria trabalho
                // repetido, mas não o desperdício.
                println!(
                    "[engine] backend já ativo na porta {}; reutilizando e não iniciando worker.",
                    self.port
                );
                let mut inner = self.inner.lock().expect("estado do motor envenenado");
                inner.reused = true;
                return Ok(());
            }
            return Err(format!(
                "A porta {} está ocupada por outro serviço. Libere a porta ou feche o processo manualmente.",
                self.port
            ));
        }

        if !port_is_free(self.port) {
            return Err(format!("A porta {} está ocupada.", self.port));
        }

        let paths = ProjectPaths::discover()?;

        self.set_phase(Phase::Migrating, None);
        self.run_migrations(&paths)?;

        self.set_phase(Phase::Starting, None);
        self.start_backend(&paths)?;
        self.start_worker(&paths)?;

        Ok(())
    }

    fn run_migrations(&self, paths: &ProjectPaths) -> Result<(), String> {
        println!("[engine] aplicando migrations");
        let output = base_command(paths)
            .args(["-m", "alembic", "upgrade", "head"])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|error| format!("Não foi possível executar o Alembic: {error}"))?;

        for line in String::from_utf8_lossy(&output.stdout).lines() {
            println!("[migrations] {line}");
        }
        for line in String::from_utf8_lossy(&output.stderr).lines() {
            eprintln!("[migrations] {line}");
        }

        if !output.status.success() {
            // Sem schema não adianta subir backend nem worker.
            return Err("Falha ao aplicar as migrations. Veja o log [migrations].".into());
        }
        Ok(())
    }

    fn start_backend(&self, paths: &ProjectPaths) -> Result<(), String> {
        println!("[engine] iniciando FastAPI na porta {}", self.port);
        let mut child = base_command(paths)
            .args([
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                &self.port.to_string(),
            ])
            .spawn()
            .map_err(|error| format!("Não foi possível iniciar o backend: {error}"))?;

        pipe_output(&mut child, "backend");

        if let Err(error) = wait_for_health(self.port, &mut child) {
            terminate(&mut child, "backend");
            return Err(error);
        }

        self.inner
            .lock()
            .expect("estado do motor envenenado")
            .backend = Some(child);
        Ok(())
    }

    fn start_worker(&self, paths: &ProjectPaths) -> Result<(), String> {
        {
            let inner = self.inner.lock().expect("estado do motor envenenado");
            if inner.worker.is_some() {
                return Ok(());
            }
        }

        println!("[engine] iniciando worker");
        let mut child = base_command(paths)
            .args(["-m", "app.worker"])
            .spawn()
            .map_err(|error| format!("Não foi possível iniciar o worker: {error}"))?;

        pipe_output(&mut child, "worker");
        self.inner
            .lock()
            .expect("estado do motor envenenado")
            .worker = Some(child);
        Ok(())
    }

    /// Encerra worker primeiro, depois backend: assim nenhum job novo começa
    /// enquanto a API ainda aceita requisições.
    pub fn shutdown(&self) {
        let (worker, backend) = {
            let mut inner = self.inner.lock().expect("estado do motor envenenado");
            (inner.worker.take(), inner.backend.take())
        };

        if let Some(mut child) = worker {
            terminate(&mut child, "worker");
        }
        if let Some(mut child) = backend {
            terminate(&mut child, "backend");
        }

        self.set_phase(Phase::Idle, None);
    }
}

#[tauri::command]
pub fn engine_status(engine: tauri::State<'_, Engine>) -> EngineStatus {
    engine.status()
}

#[tauri::command]
pub fn engine_restart(engine: tauri::State<'_, Engine>) -> EngineStatus {
    let handle = engine.inner().clone();
    handle.shutdown();
    handle.start();
    handle.status()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn recognizes_our_backend() {
        let response = "HTTP/1.1 200 OK\r\n\r\n{\"status\":\"ok\",\"name\":\"clipper-api\"}";
        assert!(is_our_backend(response));
    }

    #[test]
    fn rejects_another_service_on_the_port() {
        assert!(!is_our_backend("HTTP/1.1 200 OK\r\n\r\n{\"app\":\"outra-coisa\"}"));
        assert!(!is_our_backend("HTTP/1.1 404 Not Found\r\n\r\n"));
        assert!(!is_our_backend(""));
    }

    #[test]
    fn starts_idle() {
        let engine = Engine::new(DEFAULT_PORT);
        let status = engine.status();
        assert_eq!(status.phase, Phase::Idle);
        assert_eq!(status.port, DEFAULT_PORT);
        assert!(!status.reused);
    }

    #[test]
    fn startup_is_claimed_only_once() {
        let engine = Engine::new(DEFAULT_PORT);
        assert!(engine.claim_startup());
        assert!(!engine.claim_startup());
        engine.release_startup();
        assert!(engine.claim_startup());
    }
}
