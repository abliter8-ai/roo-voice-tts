// Roo Voice v2 shell (IP-178): supervises the roo-engine sidecar, hands its
// loopback port to the WebView, and guarantees clean teardown (engine owns a
// llama-server child — never orphan it; /shutdown first, kill as fallback).
use std::io::{BufRead, BufReader, Write};
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

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .ok_or("cannot locate app binary dir")?;
    let name = if cfg!(windows) { "roo-engine.exe" } else { "roo-engine" };
    let engine = exe_dir.join(name);
    if !engine.exists() {
        return Err(format!("engine binary missing: {}", engine.display()));
    }
    let mut c = Command::new(engine);
    c.arg("--data-dir")
        .arg(&data_dir)
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
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
        // Polite path: engine stops llama-server, then exits itself.
        if let Ok(mut s) = std::net::TcpStream::connect(("127.0.0.1", port)) {
            let _ = s.write_all(
                b"POST /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
            );
            std::thread::sleep(std::time::Duration::from_millis(600));
        }
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        match child.try_wait() {
            Ok(Some(_)) => {}
            _ => {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![get_engine_port])
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
