// NEGATIVE: should NOT flag — #[deprecated] with specific replacement

// GOOD: deprecated with exact replacement named
#[deprecated(note = "use `connect_with_tls()` instead — this function does not verify certificates")]
pub fn old_connect() -> Connection {
    todo!()
}

// GOOD: deprecated with replacement and docs link
#[deprecated(since = "2.0.0", note = "use `Config::from_str()` instead. See https://docs.rs/mylib/2.0/migration")]
pub fn legacy_parse(s: &str) -> Result<Config, Error> {
    todo!()
}
