#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod menu;
mod sidecar;
mod tray;

use serde::Serialize;
use tauri::{Emitter, Listener, Manager};
use tauri_plugin_dialog::DialogExt;

#[derive(Clone, Serialize)]
struct DeepLinkPayload {
    urls: Vec<String>,
}

#[tauri::command]
async fn select_project_directory(app: tauri::AppHandle) -> Option<String> {
    app.dialog()
        .file()
        .set_title("Select Project Directory")
        .blocking_pick_folder()
        .map(|p| p.to_string())
}

#[tauri::command]
async fn get_platform() -> String {
    std::env::consts::OS.to_string()
}

#[tauri::command]
async fn send_notification(
    app: tauri::AppHandle,
    title: String,
    body: String,
) -> Result<(), String> {
    use tauri_plugin_notification::NotificationExt;
    app.notification()
        .builder()
        .title(&title)
        .body(&body)
        .show()
        .map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .manage(sidecar::BackendProcess::new())
        .invoke_handler(tauri::generate_handler![
            select_project_directory,
            get_platform,
            send_notification,
        ])
        .setup(|app| {
            let handle = app.handle().clone();

            // Native menu
            let menu = menu::build_menu(&handle)?;
            app.set_menu(menu)?;
            menu::setup_menu_events(&handle);

            // System tray
            tray::setup_tray(&handle)?;

            // Deep link handler
            let deep_link_handle = handle.clone();
            app.listen("deep-link://new-url", move |event| {
                if let Ok(urls) = serde_json::from_str::<Vec<String>>(event.payload()) {
                    let _ = deep_link_handle.emit("deep-link", DeepLinkPayload { urls });
                }
            });

            // Start backend sidecar
            let backend_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                if sidecar::is_port_available(8420) {
                    sidecar::start_backend(&backend_handle);

                    if !sidecar::wait_for_backend().await {
                        log::error!("Backend failed to start within timeout");
                        let _ = backend_handle.emit(
                            "backend-error",
                            "Backend did not respond within the expected time.",
                        );
                        return;
                    }

                    log::info!("Backend is ready");
                    let _ = backend_handle.emit("backend-status", "ready");
                    sidecar::monitor_backend(backend_handle);
                } else {
                    log::info!("Port 8420 already in use, assuming backend is running");
                    let _ = backend_handle.emit("backend-status", "ready");
                }
            });

            // Check for updates (production only)
            #[cfg(not(debug_assertions))]
            {
                let updater_handle = handle.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = check_for_updates(updater_handle).await {
                        log::warn!("Update check failed: {}", e);
                    }
                });
            }

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                #[cfg(target_os = "macos")]
                {
                    let _ = window.hide();
                    api.prevent_close();
                }
                #[cfg(not(target_os = "macos"))]
                {
                    let app = window.app_handle();
                    sidecar::stop_backend(app);
                }
            }
            if let tauri::WindowEvent::Destroyed = event {
                let app = window.app_handle();
                sidecar::stop_backend(app);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                sidecar::stop_backend(app);
            }
        });
}

#[cfg(not(debug_assertions))]
async fn check_for_updates(app: tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    use tauri_plugin_updater::UpdaterExt;

    let updater = app.updater()?;
    if let Some(update) = updater.check().await? {
        let version = update.version.clone();
        let _ = app.emit(
            "update-status",
            serde_json::json!({
                "status": "available",
                "version": version
            }),
        );
    }
    Ok(())
}
