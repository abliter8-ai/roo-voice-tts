// Roo Voice v3 shell: supervises the roo-engine sidecar, hands its loopback
// port to the WebView, and guarantees clean teardown (the sidecar owns the
// native tts-server child — /shutdown first, kill as fallback).
use std::io::{BufRead, BufReader, Write};
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Emitter, Manager, RunEvent};

#[derive(Default)]
struct EngineState {
    port: Mutex<Option<u16>>,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn get_engine_port(state: tauri::State<EngineState>) -> Option<u16> {
    *state.port.lock().unwrap()
}

#[tauri::command]
fn save_export(app: tauri::AppHandle, name: String, bytes: Vec<u8>) -> Result<String, String> {
    let raw_name = Path::new(&name)
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| "export filename is invalid".to_string())?;
    if raw_name.is_empty() || raw_name == "." || raw_name == ".." {
        return Err("export filename is invalid".to_string());
    }
    let dir = app.path().download_dir().map_err(|e| format!("download folder unavailable: {e}"))?;
    std::fs::create_dir_all(&dir).map_err(|e| format!("cannot create download folder: {e}"))?;
    let path = Path::new(raw_name);
    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("roo-export");
    let ext = path.extension().and_then(|s| s.to_str()).map(|s| format!(".{s}")).unwrap_or_default();
    for index in 0..10_000u32 {
        let filename = if index == 0 { raw_name.to_string() } else { format!("{stem} ({index}){ext}") };
        let target = dir.join(filename);
        match OpenOptions::new().write(true).create_new(true).open(&target) {
            Ok(mut file) => {
                use std::io::Write as _;
                file.write_all(&bytes).map_err(|e| format!("cannot write export: {e}"))?;
                return Ok(target.to_string_lossy().into_owned());
            }
            Err(e) if e.kind() == ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("cannot create export: {e}")),
        }
    }
    Err("cannot choose a free export filename".to_string())
}

/// Dev builds honour ROO_ENGINE_CMD (e.g. a venv `python -m roo_engine ...`);
/// release builds run the frozen roo-engine that ships beside the app binary.
fn engine_command(app: &tauri::AppHandle) -> Result<Command, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("no app data dir: {e}"))?;
    std::fs::create_dir_all(&data_dir).map_err(|e| e.to_string())?;

    if let Ok(dev_cmd) = std::env::var("ROO_ENGINE_CMD") {
        let mut c = if cfg!(windows) {
            let mut c = Command::new("cmd");
            c.arg("/C").arg(&dev_cmd);
            c
        } else {
            let mut c = Command::new("sh");
            c.arg("-c").arg(format!("{dev_cmd} --data-dir '{}'", data_dir.display()));
            c
        };
        c.stdout(Stdio::piped()).stderr(Stdio::null());
        return Ok(c);
    }

    let name = if cfg!(windows) { "roo-engine.exe" } else { "roo-engine" };
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(res) = app.path().resource_dir() {
        candidates.push(res.join("roo-engine").join(name));
    }
    if let Some(exe_dir) = std::env::current_exe().ok().and_then(|p| p.parent().map(|p| p.to_path_buf())) {
        candidates.push(exe_dir.join("roo-engine").join(name));
        candidates.push(exe_dir.join(name));
    }
    let engine = candidates
        .iter()
        .find(|p| p.exists())
        .ok_or_else(|| format!("engine binary missing; looked in: {candidates:?}"))?;
    let mut c = Command::new(engine);
    c.arg("--data-dir").arg(&data_dir);
    let manifest = engine.parent().unwrap().join("manifest.json");
    if manifest.exists() {
        c.arg("--manifest").arg(manifest);
    }
    c.stdout(Stdio::piped()).stderr(Stdio::null());
    Ok(c)
}

fn spawn_engine(app: tauri::AppHandle) {
    std::thread::spawn(move || {
        let mut cmd = match engine_command(&app) {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit("engine-error", e);
                return;
            }
        };
        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit("engine-error", format!("spawn failed: {e}"));
                return;
            }
        };
        let stdout = child.stdout.take();
        {
            let state = app.state::<EngineState>();
            *state.child.lock().unwrap() = Some(child);
        }
        if let Some(out) = stdout {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(&line) {
                    if let Some(port) = v.get("port").and_then(|p| p.as_u64()) {
                        let state = app.state::<EngineState>();
                        *state.port.lock().unwrap() = Some(port as u16);
                        let _ = app.emit("engine-port", port);
                    }
                }
            }
        }
    });
}

fn shutdown_engine(state: &EngineState) {
    let port = *state.port.lock().unwrap();
    if let Some(port) = port {
        // Polite path: engine stops the native tts-server, then exits itself.
        if let Ok(mut s) = std::net::TcpStream::connect(("127.0.0.1", port)) {
            let _ = s.write_all(
                b"POST /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            );
        }
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        // Native shutdown can take up to ten seconds while a generation drains.
        // Allow a bounded grace period before falling back to termination.
        for _ in 0..85 {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => std::thread::sleep(std::time::Duration::from_millis(200)),
                Err(_) => break,
            }
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![get_engine_port, save_export])
        .setup(|app| {
            spawn_engine(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                shutdown_engine(&app.state::<EngineState>());
            }
        });
}
