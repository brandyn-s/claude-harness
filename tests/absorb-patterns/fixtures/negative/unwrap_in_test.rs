// NEGATIVE: should NOT flag — unwrap() in test code is acceptable

use std::fs;

fn read_config(path: &str) -> anyhow::Result<String> {
    // GOOD: uses ? operator
    let contents = fs::read_to_string(path)?;
    Ok(contents)
}

fn parse_port(s: &str) -> Result<u16, std::num::ParseIntError> {
    // GOOD: returns Result
    s.parse::<u16>()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_read_config() {
        // OK: unwrap in test code is fine
        let result = read_config("test.toml").unwrap();
        assert!(!result.is_empty());
    }

    #[test]
    fn test_parse_port() {
        // OK: unwrap in test
        let port = parse_port("8080").unwrap();
        assert_eq!(port, 8080);
    }
}
