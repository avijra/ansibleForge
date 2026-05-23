use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager};


pub const PORT: u16 = 8420;
const MAX_RESTARTS: u32 = 3;
const HEALTH_POLL_INTERVAL: Duration = Duration::from_secs(1);
const HEALTH_MAX_RETRIES: u32 = 30;
const SHUTDOWN_GRACE: Duration = Duration::from_secs(3);

static RESTART_COUNT: AtomicU32 = AtomicU32::new(0);
static INTENTIONAL_SHUTDOWN: AtomicBool = AtomicBool::new(false);

pub struct BackendProcess {
    child: Mutex<Option<Child>>,
}

impl BackendProcess {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }
}

pub fn is_port_available(port: u16) -> bool {
    std::net::TcpListener::bind(("127.0.0.1", port)).is_ok()
}

pub async fn wait_for_backend() -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();

    for _ in 0..HEALTH_MAX_RETRIES {
        match client
            .get(format!("http://127.0.0.1:{}/api/v1/health", PORT))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => return true,
            _ => {}
        }
        tokio::time::sleep(HEALTH_POLL_INTERVAL).await;
    }
    false
}

fn get_backend_command(app: &AppHandle) -> (String, Vec<String>, String) {
    let bin_name = if cfg!(target_os = "windows") {
        "ansibleforge-backend.exe"
    } else {
        "ansibleforge-backend"
    };

    // Bundled mode: backend directory is in resources/backend/
    let resource_dir = app
        .path()
        .resource_dir()
        .expect("failed to resolve resource dir");

    let backend_dir = resource_dir.join("backend");
    let backend_bin = backend_dir.join(bin_name);

    log::info!(
        "Looking for backend at: {} (exists={})",
        backend_bin.display(),
        backend_bin.exists()
    );

    if backend_bin.exists() {
        return (
            backend_bin.to_string_lossy().to_string(),
            vec![],
            backend_dir.to_string_lossy().to_string(),
        );
    }

    // Fallback: next to main executable (for older builds)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let sidecar = exe_dir.join(bin_name);
            if sidecar.exists() {
                return (
                    sidecar.to_string_lossy().to_string(),
                    vec![],
                    exe_dir.to_string_lossy().to_string(),
                );
            }
        }
    }

    // Dev mode: run from Python
    let project_root = std::env::current_dir().unwrap_or_else(|_| {
        app.path()
            .resource_dir()
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf()
    });

    let venv_python = project_root.join(".venv").join("bin").join("python");
    let python_cmd = if venv_python.exists() {
        venv_python.to_string_lossy().to_string()
    } else if cfg!(target_os = "windows") {
        "python".to_string()
    } else {
        "python3".to_string()
    };

    (
        python_cmd,
        vec!["-m".to_string(), "ansible_forge.main".to_string()],
        project_root.to_string_lossy().to_string(),
    )
}

pub fn start_backend(app: &AppHandle) {
    let (cmd, args, cwd) = get_backend_command(app);
    let pid = std::process::id();

    log::info!("Starting backend: {} {:?} (cwd: {})", cmd, args, cwd);

    let mut command = Command::new(&cmd);
    command
        .args(&args)
        .current_dir(&cwd)
        .env("ANSIBLEFORGE_HOST", "127.0.0.1")
        .env("ANSIBLEFORGE_PORT", PORT.to_string())
        .env("ANSIBLEFORGE_PARENT_PID", pid.to_string());

    // Ensure bundled Python/OpenSSL can find CA certificates for HTTPS
    // (PyInstaller binaries lose access to build-machine cert paths)
    let backend_dir = std::path::Path::new(&cwd);
    let bundled_ca = backend_dir
        .join("_internal")
        .join("certifi")
        .join("cacert.pem");
    if bundled_ca.exists() {
        let ca_str = bundled_ca.to_string_lossy().to_string();
        command.env("SSL_CERT_FILE", &ca_str);
        command.env("REQUESTS_CA_BUNDLE", &ca_str);
        log::info!("Setting SSL_CERT_FILE={}", ca_str);
    } else {
        // Fallback to system CA bundles
        for path in &[
            "/etc/ssl/cert.pem",
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/pki/tls/certs/ca-bundle.crt",
        ] {
            if std::path::Path::new(path).exists() {
                command.env("SSL_CERT_FILE", path);
                command.env("REQUESTS_CA_BUNDLE", path);
                log::info!("Setting SSL_CERT_FILE={} (system fallback)", path);
                break;
            }
        }
    }

    command
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    match command.spawn()
    {
        Ok(mut child) => {
            if let Some(stdout) = child.stdout.take() {
                std::thread::spawn(move || {
                    let reader = std::io::BufReader::new(stdout);
                    for line in std::io::BufRead::lines(reader) {
                        match line {
                            Ok(l) => log::debug!("[backend:out] {}", l),
                            Err(_) => break,
                        }
                    }
                });
            }
            if let Some(stderr) = child.stderr.take() {
                std::thread::spawn(move || {
                    let reader = std::io::BufReader::new(stderr);
                    for line in std::io::BufRead::lines(reader) {
                        match line {
                            Ok(l) => log::debug!("[backend:err] {}", l),
                            Err(_) => break,
                        }
                    }
                });
            }

            let state = app.state::<BackendProcess>();
            *state.child.lock().unwrap() = Some(child);
            log::info!("Backend process started");
        }
        Err(e) => {
            log::error!("Failed to start backend: {}", e);
            if !INTENTIONAL_SHUTDOWN.load(Ordering::SeqCst) {
                let _ = app.emit("backend-error", format!("Failed to start backend: {}", e));
            }
        }
    }
}

pub fn stop_backend(app: &AppHandle) {
    INTENTIONAL_SHUTDOWN.store(true, Ordering::SeqCst);
    let state = app.state::<BackendProcess>();
    let mut guard = state.child.lock().unwrap();

    if let Some(ref mut child) = *guard {
        let child_id = child.id();
        graceful_kill(child_id);
    }
    *guard = None;
}

fn graceful_kill(pid: u32) {
    #[cfg(unix)]
    {
        unsafe { libc::kill(pid as i32, libc::SIGTERM) };
        let p = pid;
        std::thread::spawn(move || {
            std::thread::sleep(SHUTDOWN_GRACE);
            unsafe { libc::kill(p as i32, libc::SIGKILL) };
        });
    }
    #[cfg(not(unix))]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F"])
            .spawn();
    }
}

pub fn monitor_backend(app: AppHandle) {
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_secs(2));

        if INTENTIONAL_SHUTDOWN.load(Ordering::SeqCst) {
            break;
        }

        let state = app.state::<BackendProcess>();
        let mut guard = state.child.lock().unwrap();

        if let Some(ref mut child) = *guard {
            match child.try_wait() {
                Ok(Some(status)) => {
                    log::warn!("Backend exited with status: {:?}", status);
                    *guard = None;
                    drop(guard);

                    if !INTENTIONAL_SHUTDOWN.load(Ordering::SeqCst) {
                        let count = RESTART_COUNT.fetch_add(1, Ordering::SeqCst) + 1;
                        if count <= MAX_RESTARTS {
                            log::info!(
                                "Restarting backend (attempt {}/{})",
                                count,
                                MAX_RESTARTS
                            );
                            std::thread::sleep(Duration::from_secs(1));
                            start_backend(&app);

                            let app_clone = app.clone();
                            tauri::async_runtime::spawn(async move {
                                if wait_for_backend().await {
                                    let _ =
                                        app_clone.emit("backend-status", "backend-restarted");
                                }
                            });
                        } else {
                            log::error!("Backend crashed repeatedly, giving up");
                            let _ = app.emit(
                                "backend-error",
                                "Backend has crashed repeatedly and cannot be recovered.",
                            );
                            break;
                        }
                    }
                }
                Ok(None) => {}
                Err(e) => {
                    log::error!("Error checking backend status: {}", e);
                }
            }
        }
    });
}
