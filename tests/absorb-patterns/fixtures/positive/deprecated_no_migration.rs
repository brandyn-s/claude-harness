// POSITIVE: should flag — #[deprecated] without migration path

// BAD: deprecated with no guidance
#[deprecated]
pub fn old_connect() -> Connection {
    todo!()
}

// BAD: deprecated with vague note
#[deprecated(note = "use the new API")]
pub fn legacy_parse(s: &str) -> Result<Config, Error> {
    todo!()
}
