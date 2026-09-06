mod engine;

use engine::{Engine, DEFAULT_PORT};

/// Inicia o app e, junto, o motor local (migrations, FastAPI e worker).
///
/// O startup roda numa thread própria para não segurar a abertura da janela:
/// a interface aparece já mostrando "Iniciando motor…" e consulta o estado.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let engine = Engine::new(DEFAULT_PORT);
    let for_setup = engine.clone();
    let for_exit = engine.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(engine)
        .invoke_handler(tauri::generate_handler![
            engine::engine_status,
            engine::engine_restart
        ])
        .setup(move |_app| {
            std::thread::spawn(move || for_setup.start());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("erro ao iniciar a aplicação Tauri")
        .run(move |_app_handle, event| {
            // Encerra os processos filhos antes de o processo Tauri sair.
            if let tauri::RunEvent::Exit = event {
                for_exit.shutdown();
            }
        });
}
