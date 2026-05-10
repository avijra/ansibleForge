use tauri::{
    menu::{AboutMetadataBuilder, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder},
    AppHandle, Emitter,
};

pub fn build_menu(app: &AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    let settings = MenuItemBuilder::new("Settings")
        .id("settings")
        .accelerator("CmdOrCtrl+,")
        .build(app)?;

    let cmd_palette = MenuItemBuilder::new("Command Palette")
        .id("command-palette")
        .accelerator("CmdOrCtrl+K")
        .build(app)?;

    let toggle_sidebar = MenuItemBuilder::new("Toggle Sidebar")
        .id("toggle-sidebar")
        .accelerator("CmdOrCtrl+B")
        .build(app)?;

    let toggle_terminal = MenuItemBuilder::new("Toggle Terminal")
        .id("toggle-terminal")
        .accelerator("CmdOrCtrl+`")
        .build(app)?;

    let docs = MenuItemBuilder::new("Documentation")
        .id("docs")
        .build(app)?;

    let report_issue = MenuItemBuilder::new("Report Issue")
        .id("report-issue")
        .build(app)?;

    let about_meta = AboutMetadataBuilder::new()
        .name(Some("Tuyere"))
        .version(Some(env!("CARGO_PKG_VERSION")))
        .build();

    let app_submenu = SubmenuBuilder::new(app, "Tuyere")
        .about(Some(about_meta))
        .separator()
        .item(&settings)
        .separator()
        .quit()
        .build()?;

    let edit_submenu = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    let view_submenu = SubmenuBuilder::new(app, "View")
        .item(&cmd_palette)
        .item(&toggle_sidebar)
        .item(&toggle_terminal)
        .separator()
        .item(&PredefinedMenuItem::fullscreen(app, None)?)
        .build()?;

    let help_submenu = SubmenuBuilder::new(app, "Help")
        .item(&docs)
        .item(&report_issue)
        .build()?;

    let menu = MenuBuilder::new(app)
        .items(&[&app_submenu, &edit_submenu, &view_submenu, &help_submenu])
        .build()?;

    Ok(menu)
}

pub fn setup_menu_events(app: &AppHandle) {
    let handle = app.clone();
    app.on_menu_event(move |_app, event| {
        match event.id().as_ref() {
            "settings" => {
                let _ = handle.emit("open-settings", ());
            }
            "command-palette" => {
                let _ = handle.emit("toggle-command-palette", ());
            }
            "toggle-sidebar" => {
                let _ = handle.emit("toggle-sidebar", ());
            }
            "toggle-terminal" => {
                let _ = handle.emit("toggle-terminal", ());
            }
            "docs" => {
                let _ = tauri_plugin_opener::open_url("https://github.com/avijra/ansibleForge", None::<&str>);
            }
            "report-issue" => {
                let _ = tauri_plugin_opener::open_url(
                    "https://github.com/avijra/ansibleForge/issues",
                    None::<&str>,
                );
            }
            _ => {}
        }
    });
}
