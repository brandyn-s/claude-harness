// POSITIVE: should flag — unwrap() in non-test application code

use std::fs;

fn read_config() -> String {
    // BAD: unwrap in app code — should use ? or expect with justification
    let contents = fs::read_to_string("config.toml").unwrap();
    contents
}

fn parse_port(s: &str) -> u16 {
    // BAD: unwrap on parse
    s.parse::<u16>().unwrap()
}

fn get_connection() -> Connection {
    // BAD: unwrap on network operation
    let conn = TcpStream::connect("127.0.0.1:5432").unwrap();
    conn
}
