// NEGATIVE: should NOT flag — uses tracing properly

use tracing::{info, warn, error, debug};

fn start_server(port: u16) {
    // GOOD: structured tracing
    info!(port = %port, "Starting server");

    // GOOD: tracing for warnings
    warn!("TLS not configured");
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_output() {
        // OK: println in tests is fine
        println!("Test output for debugging");
    }
}
