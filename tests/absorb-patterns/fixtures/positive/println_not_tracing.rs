// POSITIVE: should flag — println/eprintln instead of tracing

fn start_server(port: u16) {
    // BAD: println for logging
    println!("Starting server on port {}", port);

    // BAD: eprintln for errors
    eprintln!("Warning: TLS not configured");

    // BAD: dbg! left in production code
    dbg!(port);
}
